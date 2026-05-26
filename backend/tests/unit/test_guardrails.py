"""Unit tests for guardrails.py — approval flow and audit logging.

Tests the core logic (policy evaluation, risk classification) directly without
Redis or DB dependencies by mocking external I/O. This is intentional: the
business logic is in evaluate_guardrail's branching tree, which must be correct
regardless of storage backend.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.guardrails import (
    GuardrailLevel,
    ApprovalStatus,
    ApprovalRequest,
    AuditEntry,
    evaluate_guardrail,
    resolve_approval,
    get_pending_approvals,
    get_audit_log,
    IRREVERSIBLE_ACTIONS,
    WARN_ACTIONS,
    STAGE_GUARDRAILS,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Patch get_redis and cache_set/cache_get for all guardrail calls."""
    fake_redis = AsyncMock()
    fake_redis.sadd = AsyncMock(return_value=1)
    fake_redis.srem = AsyncMock(return_value=1)
    fake_redis.zadd = AsyncMock(return_value=1)
    fake_redis.zcard = AsyncMock(return_value=0)
    fake_redis.zremrangebyrank = AsyncMock(return_value=0)
    fake_redis.smembers = AsyncMock(return_value=set())
    fake_redis.zrange = AsyncMock(return_value=[])
    fake_redis.zrevrange = AsyncMock(return_value=[])

    with patch('app.services.guardrails.get_redis', return_value=fake_redis), \
         patch('app.services.guardrails.cache_set', AsyncMock()), \
         patch('app.services.guardrails.cache_get', AsyncMock(return_value=None)):
        yield fake_redis


@pytest.fixture
def mock_db():
    """Patch async_session so no real DB is touched."""
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    fake_session.execute.return_value.scalars = MagicMock()
    fake_session.execute.return_value.scalars.return_value.all = MagicMock(return_value=[])

    with patch('app.services.guardrails.async_session', return_value=fake_session):
        yield fake_session


# ── evaluate_guardrail ─────────────────────────────────────────────────────

class TestEvaluateGuardrail:
    """Core policy evaluation — tests the decision tree without I/O."""

    async def test_auto_approve_safe_action(self, mock_redis, mock_db):
        result = await evaluate_guardrail(
            action="read_data", stage_id="planning",
            role="developer", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.AUTO_APPROVE
        assert result["proceed"] is True

    async def test_warn_for_warn_actions(self, mock_redis, mock_db):
        for action in WARN_ACTIONS:
            result = await evaluate_guardrail(
                action=action, stage_id="planning",
                role="developer", task_id="task-1",
            )
            assert result["level"] == GuardrailLevel.WARN
            assert result["proceed"] is True
            assert "审计日志" in result.get("reason", "")

    async def test_block_for_unauthorized_irreversible(self, mock_redis, mock_db):
        result = await evaluate_guardrail(
            action="deploy_production", stage_id="deploy",
            role="qa", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.BLOCK
        assert result["proceed"] is False
        assert "无权" in result.get("reason", "")

    async def test_require_review_for_authorized_irreversible(self, mock_redis, mock_db):
        result = await evaluate_guardrail(
            action="deploy_production", stage_id="deploy",
            role="admin", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.REQUIRE_REVIEW
        assert result["proceed"] is False
        assert result.get("approval_id") is not None

    async def test_require_review_for_security_stage(self, mock_redis, mock_db):
        result = await evaluate_guardrail(
            action="code_review", stage_id="security-review",
            role="developer", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.REQUIRE_REVIEW
        assert result["proceed"] is False

    @pytest.mark.parametrize("action", sorted(IRREVERSIBLE_ACTIONS))
    async def test_all_irreversible_actions_require_review(self, mock_redis, mock_db, action):
        """Every irreversible action needs an admin-equivalent role."""
        result = await evaluate_guardrail(
            action=action, stage_id="deploy",
            role="developer", task_id="task-1",
        )
        assert result["proceed"] is False
        assert result["level"] in (GuardrailLevel.BLOCK, GuardrailLevel.REQUIRE_REVIEW)

    @pytest.mark.parametrize("action,expected_level", [
        ("deploy_staging", GuardrailLevel.REQUIRE_REVIEW),
        ("create_branch", GuardrailLevel.WARN),
    ])
    async def test_developer_can_perform_own_actions(self, mock_redis, mock_db, action, expected_level):
        result = await evaluate_guardrail(
            action=action, stage_id="planning",
            role="developer", task_id="task-1",
        )
        assert result["level"] == expected_level

    async def test_default_role_qa_has_no_permissions(self, mock_redis, mock_db):
        """QA role should have no permissions per defaults."""
        for action in IRREVERSIBLE_ACTIONS:
            result = await evaluate_guardrail(
                action=action, stage_id="deploy",
                role="qa", task_id="task-1",
            )
            assert result["proceed"] is False

    async def test_unknown_action_defaults_to_auto_approve(self, mock_redis, mock_db):
        result = await evaluate_guardrail(
            action="unknown_action_xyz", stage_id="planning",
            role="developer", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.AUTO_APPROVE
        assert result["proceed"] is True

    async def test_stage_guardrail_has_correct_levels(self, mock_redis, mock_db):
        """STAGE_GUARDRAILS is checked but only REQUIRE_REVIEW blocks."""
        # acceptance is WARN → doesn't trigger stage-level block
        result = await evaluate_guardrail(
            action="accept_delivery", stage_id="acceptance",
            role="admin", task_id="task-1",
        )
        assert result["proceed"] is True

        # security-review is REQUIRE_REVIEW → blocks
        result = await evaluate_guardrail(
            action="code_review", stage_id="security-review",
            role="developer", task_id="task-1",
        )
        assert result["level"] == GuardrailLevel.REQUIRE_REVIEW
        assert result["proceed"] is False


# ── Resolve Approval ───────────────────────────────────────────────────────

class TestResolveApproval:
    async def test_approve_existing(self, mock_redis, mock_db):
        approval = ApprovalRequest(
            task_id="task-1", stage_id="deploy",
            action="deploy_production", description="Test",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
        )
        # Mock cache_get to return this approval
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=approval.dict())):
            result = await resolve_approval(
                approval_id=approval.id,
                approved=True,
                reviewer="admin",
                comment="Looks good",
            )
            assert result is not None
            assert result.status == ApprovalStatus.APPROVED
            assert result.reviewer == "admin"
            assert result.review_comment == "Looks good"
            assert result.resolved_at is not None

    async def test_reject_approval(self, mock_redis, mock_db):
        approval = ApprovalRequest(
            task_id="task-1", stage_id="deploy",
            action="deploy_production", description="Test",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
        )
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=approval.dict())):
            result = await resolve_approval(
                approval_id=approval.id,
                approved=False,
                reviewer="admin",
                comment="Not ready",
            )
            assert result is not None
            assert result.status == ApprovalStatus.REJECTED
            assert result.review_comment == "Not ready"

    async def test_approve_nonexistent(self, mock_redis, mock_db):
        result = await resolve_approval(
            approval_id="nonexistent",
            approved=True,
            reviewer="admin",
        )
        assert result is None


# ── Pending Approvals ──────────────────────────────────────────────────────

class TestGetPendingApprovals:
    async def test_empty_returns_empty_list(self, mock_redis, mock_db):
        approvals = await get_pending_approvals()
        assert approvals == []

    async def test_with_pending_in_redis(self, mock_redis, mock_db):
        approval = ApprovalRequest(
            task_id="task-1", stage_id="deploy",
            action="deploy_production", description="Test",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
        )
        # Mock Redis to return the approval ID
        mock_redis.smembers.return_value = {approval.id}
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=approval.dict())):
            approvals = await get_pending_approvals()
            assert len(approvals) == 1
            assert approvals[0].id == approval.id
            assert approvals[0].status == ApprovalStatus.PENDING

    async def test_task_filtered_pending(self, mock_redis, mock_db):
        approval = ApprovalRequest(
            task_id="task-specific", stage_id="deploy",
            action="deploy_production", description="Test",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
        )
        mock_redis.zrange.return_value = [approval.id]
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=approval.dict())):
            approvals = await get_pending_approvals(task_id="task-specific")
            assert len(approvals) == 1
            mock_redis.zrange.assert_called_with("approvals:task:task-specific", 0, -1)


# ── Audit Log ──────────────────────────────────────────────────────────────

class TestGetAuditLog:
    async def test_empty_audit_log(self, mock_redis, mock_db):
        entries = await get_audit_log()
        assert entries == []

    async def test_with_entries_in_redis(self, mock_redis, mock_db):
        entry = AuditEntry(
            task_id="task-1", stage_id="deploy",
            action="deploy_production", actor="admin",
            risk_level="require_review", outcome="approved",
        )
        mock_redis.zrevrange.return_value = [entry.id]
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=entry.dict())):
            entries = await get_audit_log()
            assert len(entries) == 1
            assert entries[0].action == "deploy_production"
            assert entries[0].outcome == "approved"

    async def test_task_filtered_audit(self, mock_redis, mock_db):
        entry = AuditEntry(
            task_id="task-a", stage_id="planning",
            action="schema_migration", actor="devops",
            risk_level="warn", outcome="auto_approved",
        )
        mock_redis.zrevrange.return_value = [entry.id]
        with patch('app.services.guardrails.cache_get',
                   AsyncMock(return_value=entry.dict())):
            entries = await get_audit_log(task_id="task-a")
            assert len(entries) == 1


# ── Policy Definitions ────────────────────────────────────────────────────

class TestPolicyDefinitions:
    def test_irreversible_actions_defined(self):
        assert "deploy_production" in IRREVERSIBLE_ACTIONS
        assert "delete_data" in IRREVERSIBLE_ACTIONS
        assert "billing_change" in IRREVERSIBLE_ACTIONS

    def test_warn_actions_defined(self):
        assert "schema_migration" in WARN_ACTIONS
        assert "bulk_update" in WARN_ACTIONS

    def test_stage_guardrails_defined(self):
        assert STAGE_GUARDRAILS["security-review"] == GuardrailLevel.REQUIRE_REVIEW
        assert STAGE_GUARDRAILS["acceptance"] == GuardrailLevel.WARN

    def test_guardrail_level_values(self):
        assert GuardrailLevel.AUTO_APPROVE.value == "auto_approve"
        assert GuardrailLevel.WARN.value == "warn"
        assert GuardrailLevel.REQUIRE_REVIEW.value == "require_review"
        assert GuardrailLevel.BLOCK.value == "block"

    def test_approval_status_values(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.EXPIRED.value == "expired"
