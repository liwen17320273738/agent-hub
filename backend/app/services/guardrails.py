"""
Guardrail Mechanism — 不可逆操作审批流 + 安全护栏 (Redis + PostgreSQL)

Dual-write architecture:
- Redis: hot cache for pending approvals, recent audit log (TTL-based)
- PostgreSQL: permanent store for all approvals and audit entries

护栏层级:
1. Auto-approve:  可逆、低风险操作
2. Warn:          中等风险，记录 audit log
3. Require-review: 高风险，暂停流水线等待人工审批
4. Block:         禁止操作
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel
from sqlalchemy import select, desc

from ..models.observability import AuditLog, ApprovalRecord
from ..database import async_session
from ..redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger(__name__)

APPROVAL_TTL = 7 * 24 * 3600       # 7 days
AUDIT_ENTRY_TTL = 30 * 24 * 3600   # 30 days
AUDIT_LOG_MAX = 10_000
AUDIT_LOG_TRIM_TO = 5_000


class GuardrailLevel(str, Enum):
    AUTO_APPROVE = "auto_approve"
    WARN = "warn"
    REQUIRE_REVIEW = "require_review"
    BLOCK = "block"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    id: str = ""
    task_id: str
    stage_id: str
    action: str  # e.g. "deploy", "delete_data", "publish", "merge"
    description: str
    risk_level: GuardrailLevel
    requested_by: str = "system"
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: str = ""
    resolved_at: Optional[str] = None
    metadata: Dict[str, Any] = {}

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


class AuditEntry(BaseModel):
    id: str = ""
    task_id: str
    stage_id: str
    action: str
    actor: str  # agent role or user id
    risk_level: str
    outcome: str  # approved / rejected / auto_approved / blocked
    details: str = ""
    created_at: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


# --- Policy Definitions ---

IRREVERSIBLE_ACTIONS = {
    "deploy_production",
    "deploy_staging",
    "delete_data",
    "delete_database",
    "publish_release",
    "merge_to_main",
    "revoke_access",
    "billing_change",
    "api_key_rotate",
}

WARN_ACTIONS = {
    "schema_migration",
    "bulk_update",
    "send_notification",
    "create_branch",
}

STAGE_GUARDRAILS: Dict[str, GuardrailLevel] = {
    "acceptance": GuardrailLevel.WARN,
    "security-review": GuardrailLevel.REQUIRE_REVIEW,
}

_DEFAULT_ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "admin": ["deploy_production", "publish_release", "billing_change", "merge_to_main", "api_key_rotate", "revoke_access"],
    "cto": ["deploy_production", "schema_migration", "merge_to_main"],
    "devops": ["deploy_production", "deploy_staging", "schema_migration"],
    "developer": ["deploy_staging", "create_branch"],
    "qa": [],
    "product": [],
}


def _load_role_permissions() -> Dict[str, List[str]]:
    """Load role permissions from environment or fall back to defaults.

    Set GUARDRAIL_ROLE_PERMISSIONS as JSON to override, e.g.:
    GUARDRAIL_ROLE_PERMISSIONS='{"admin":["deploy_production"]}'
    """
    import os
    raw = os.environ.get("GUARDRAIL_ROLE_PERMISSIONS", "")
    if raw:
        try:
            import json
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("[guardrail] Invalid GUARDRAIL_ROLE_PERMISSIONS JSON, using defaults")
    return _DEFAULT_ROLE_PERMISSIONS


ROLE_PERMISSIONS: Dict[str, List[str]] = _load_role_permissions()


# --- Redis key helpers ---

def _approval_key(approval_id: str) -> str:
    return f"approval:{approval_id}"


def _audit_entry_key(entry_id: str) -> str:
    return f"audit:entry:{entry_id}"


async def _store_approval(approval: ApprovalRequest) -> None:
    """Persist an approval to Redis + PostgreSQL."""
    r = get_redis()
    await cache_set(_approval_key(approval.id), approval.dict(), ttl=APPROVAL_TTL)
    await r.sadd("approvals:pending", approval.id)
    ts = datetime.fromisoformat(approval.created_at).timestamp()
    await r.zadd(f"approvals:task:{approval.task_id}", {approval.id: ts})

    try:
        async with async_session() as db:
            record = ApprovalRecord(
                approval_id=approval.id,
                task_id=approval.task_id,
                stage_id=approval.stage_id,
                action=approval.action,
                description=approval.description,
                risk_level=approval.risk_level.value if hasattr(approval.risk_level, 'value') else str(approval.risk_level),
                requested_by=approval.requested_by,
                status=approval.status.value if hasattr(approval.status, 'value') else str(approval.status),
                metadata_extra=approval.metadata,
            )
            db.add(record)
            await db.commit()
    except Exception as e:
        logger.error(f"[guardrail] DB persist approval failed — approval data may be lost: {e}")


async def _get_approval(approval_id: str) -> Optional[ApprovalRequest]:
    """Load an approval: Redis first, DB fallback."""
    data = await cache_get(_approval_key(approval_id))
    if data is not None:
        return ApprovalRequest(**data)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                return ApprovalRequest(
                    id=rec.approval_id,
                    task_id=rec.task_id,
                    stage_id=rec.stage_id,
                    action=rec.action,
                    description=rec.description,
                    risk_level=GuardrailLevel(rec.risk_level),
                    requested_by=rec.requested_by,
                    status=ApprovalStatus(rec.status),
                    reviewer=rec.reviewer,
                    review_comment=rec.review_comment,
                    created_at=rec.created_at.isoformat() if rec.created_at else "",
                    resolved_at=rec.resolved_at.isoformat() if rec.resolved_at else None,
                    metadata=rec.metadata_extra or {},
                )
    except Exception as e:
        logger.warning(f"[guardrail] DB load approval failed: {e}")

    return None


# --- Public API ---

async def evaluate_guardrail(
    action: str,
    stage_id: str,
    role: str,
    task_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluate whether an action should proceed, warn, require approval, or be blocked.
    Returns: {"level": ..., "proceed": bool, "approval_id": ... or None}
    """
    if action in IRREVERSIBLE_ACTIONS:
        allowed_roles = [r for r, perms in ROLE_PERMISSIONS.items() if action in perms]

        if role not in allowed_roles:
            await _log_audit(task_id, stage_id, action, role, "blocked", f"Role {role} lacks permission")
            return {
                "level": GuardrailLevel.BLOCK,
                "proceed": False,
                "reason": f"角色 {role} 无权执行 {action}，需要 {', '.join(allowed_roles)} 授权",
            }

        approval = ApprovalRequest(
            task_id=task_id,
            stage_id=stage_id,
            action=action,
            description=f"不可逆操作: {action}",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
            requested_by=role,
            metadata=context or {},
        )
        await _store_approval(approval)
        await _log_audit(task_id, stage_id, action, role, "pending_approval", f"Approval ID: {approval.id}")

        return {
            "level": GuardrailLevel.REQUIRE_REVIEW,
            "proceed": False,
            "approval_id": approval.id,
            "reason": f"操作 {action} 需要人工审批",
        }

    if action in WARN_ACTIONS:
        await _log_audit(task_id, stage_id, action, role, "auto_approved_with_warning", "")
        return {
            "level": GuardrailLevel.WARN,
            "proceed": True,
            "reason": f"操作 {action} 已记录审计日志",
        }

    stage_level = STAGE_GUARDRAILS.get(stage_id)
    if stage_level == GuardrailLevel.REQUIRE_REVIEW:
        approval = ApprovalRequest(
            task_id=task_id,
            stage_id=stage_id,
            action=action,
            description=f"阶段 {stage_id} 需要审批",
            risk_level=GuardrailLevel.REQUIRE_REVIEW,
            requested_by=role,
        )
        await _store_approval(approval)
        return {
            "level": GuardrailLevel.REQUIRE_REVIEW,
            "proceed": False,
            "approval_id": approval.id,
            "reason": f"阶段 {stage_id} 需要人工审批后继续",
        }

    await _log_audit(task_id, stage_id, action, role, "auto_approved", "")
    return {"level": GuardrailLevel.AUTO_APPROVE, "proceed": True}


async def resolve_approval(
    approval_id: str,
    approved: bool,
    reviewer: str,
    comment: str = "",
) -> Optional[ApprovalRequest]:
    """Approve or reject a pending approval request."""
    approval = await _get_approval(approval_id)
    if not approval:
        return None

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.reviewer = reviewer
    approval.review_comment = comment
    approval.resolved_at = datetime.utcnow().isoformat()

    await cache_set(_approval_key(approval.id), approval.dict(), ttl=APPROVAL_TTL)

    r = get_redis()
    await r.srem("approvals:pending", approval.id)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = approval.status.value
                rec.reviewer = reviewer
                rec.review_comment = comment
                rec.resolved_at = datetime.utcnow()
                await db.commit()
    except Exception as e:
        logger.error(f"[guardrail] DB update approval resolution failed — may cause stale state: {e}")

    outcome = "approved" if approved else "rejected"
    await _log_audit(
        approval.task_id, approval.stage_id, approval.action,
        reviewer, outcome, comment,
    )

    return approval


async def get_pending_approvals(task_id: Optional[str] = None) -> List[ApprovalRequest]:
    """Get all pending approval requests — Redis first, DB fallback."""
    approvals: List[ApprovalRequest] = []

    try:
        r = get_redis()
        if task_id:
            ids = await r.zrange(f"approvals:task:{task_id}", 0, -1)
        else:
            ids = await r.smembers("approvals:pending")

        for aid in ids:
            a = await _get_approval(aid)
            if a and a.status == ApprovalStatus.PENDING:
                approvals.append(a)

        if approvals:
            return approvals
    except Exception as redis_err:
        logger.warning(f"[guardrail] Redis unavailable for approvals, falling back to DB: {redis_err}")

    try:
        async with async_session() as db:
            stmt = select(ApprovalRecord).where(ApprovalRecord.status == "pending")
            if task_id:
                stmt = stmt.where(ApprovalRecord.task_id == task_id)
            result = await db.execute(stmt.order_by(desc(ApprovalRecord.created_at)))
            for rec in result.scalars().all():
                approvals.append(ApprovalRequest(
                    id=rec.approval_id, task_id=rec.task_id, stage_id=rec.stage_id,
                    action=rec.action, description=rec.description,
                    risk_level=GuardrailLevel(rec.risk_level),
                    requested_by=rec.requested_by,
                    status=ApprovalStatus(rec.status),
                    reviewer=rec.reviewer, review_comment=rec.review_comment,
                    created_at=rec.created_at.isoformat() if rec.created_at else "",
                    metadata=rec.metadata_extra or {},
                ))
    except Exception as e:
        logger.warning(f"[guardrail] DB fallback for pending approvals failed: {e}")

    return approvals


async def get_audit_log(
    task_id: Optional[str] = None,
    limit: int = 100,
) -> List[AuditEntry]:
    """Get audit log entries, newest first — Redis first, DB fallback."""
    entries: List[AuditEntry] = []

    try:
        r = get_redis()
        if task_id:
            ids = await r.zrevrange(f"audit:task:{task_id}", 0, limit - 1)
        else:
            ids = await r.zrevrange("audit:log", 0, limit - 1)

        for eid in ids:
            data = await cache_get(_audit_entry_key(eid))
            if data:
                entries.append(AuditEntry(**data))

        if entries:
            return entries
    except Exception as redis_err:
        logger.warning(f"[guardrail] Redis unavailable for audit log, falling back to DB: {redis_err}")

    try:
        async with async_session() as db:
            stmt = select(AuditLog)
            if task_id:
                stmt = stmt.where(AuditLog.task_id == task_id)
            stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)
            result = await db.execute(stmt)
            for rec in result.scalars().all():
                entries.append(AuditEntry(
                    id=str(rec.id), task_id=rec.task_id, stage_id=rec.stage_id,
                    action=rec.action, actor=rec.actor, risk_level=rec.risk_level,
                    outcome=rec.outcome, details=rec.details,
                    created_at=rec.created_at.isoformat() if rec.created_at else "",
                ))
    except Exception as e:
        logger.warning(f"[guardrail] DB fallback for audit log failed: {e}")

    return entries


async def _log_audit(
    task_id: str,
    stage_id: str,
    action: str,
    actor: str,
    outcome: str,
    details: str,
) -> None:
    risk = GuardrailLevel.WARN.value if action in WARN_ACTIONS else GuardrailLevel.AUTO_APPROVE.value

    entry = AuditEntry(
        task_id=task_id,
        stage_id=stage_id,
        action=action,
        actor=actor,
        risk_level=risk,
        outcome=outcome,
        details=details,
    )

    r = get_redis()
    await cache_set(_audit_entry_key(entry.id), entry.dict(), ttl=AUDIT_ENTRY_TTL)

    ts = datetime.fromisoformat(entry.created_at).timestamp()
    await r.zadd("audit:log", {entry.id: ts})
    await r.zadd(f"audit:task:{task_id}", {entry.id: ts})

    count = await r.zcard("audit:log")
    if count > AUDIT_LOG_MAX:
        await r.zremrangebyrank("audit:log", 0, count - AUDIT_LOG_TRIM_TO - 1)

    try:
        async with async_session() as db:
            record = AuditLog(
                task_id=task_id,
                stage_id=stage_id,
                action=action,
                actor=actor,
                risk_level=risk,
                outcome=outcome,
                details=details,
            )
            db.add(record)
            await db.commit()
    except Exception as e:
        logger.error(f"[guardrail] DB persist audit entry failed — compliance data may be lost: {e}")

    logger.info(f"[guardrail] {outcome}: {action} by {actor} on task={task_id}/{stage_id}")
