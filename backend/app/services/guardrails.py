"""
Guardrail Mechanism — 不可逆操作审批流 + 安全护栏

护栏层级:
1. Auto-approve:  可逆、低风险操作 (文档生成、代码审查)
2. Warn:          中等风险，记录 audit log，但允许继续
3. Require-review: 高风险，暂停流水线等待人工审批
4. Block:         禁止操作 (如未授权的生产部署)

审批流:
- 需要审批的操作生成 ApprovalRequest
- 通过 SSE 通知前端
- 人工审批后继续或拒绝
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel

logger = logging.getLogger(__name__)


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


# In-memory stores (production: move to DB)
_pending_approvals: Dict[str, ApprovalRequest] = {}
_audit_log: List[AuditEntry] = []


# --- Policy Definitions ---

IRREVERSIBLE_ACTIONS = {
    "deploy_production",
    "delete_data",
    "delete_database",
    "publish_release",
    "merge_to_main",
    "revoke_access",
    "billing_change",
    "api_key_rotate",
}

WARN_ACTIONS = {
    "deploy_staging",
    "schema_migration",
    "bulk_update",
    "send_notification",
    "create_branch",
}

STAGE_GUARDRAILS: Dict[str, GuardrailLevel] = {
    "deployment": GuardrailLevel.WARN,
    "acceptance": GuardrailLevel.WARN,
    "security-review": GuardrailLevel.WARN,
}

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "wayne-ceo": ["deploy_production", "publish_release", "billing_change", "merge_to_main"],
    "wayne-cto": ["deploy_production", "schema_migration", "merge_to_main"],
    "wayne-devops": ["deploy_production", "deploy_staging", "schema_migration"],
    "wayne-developer": ["deploy_staging", "create_branch"],
    "wayne-qa": [],
    "wayne-product": [],
}


def evaluate_guardrail(
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
            _log_audit(task_id, stage_id, action, role, "blocked", f"Role {role} lacks permission")
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
        _pending_approvals[approval.id] = approval
        _log_audit(task_id, stage_id, action, role, "pending_approval", f"Approval ID: {approval.id}")

        return {
            "level": GuardrailLevel.REQUIRE_REVIEW,
            "proceed": False,
            "approval_id": approval.id,
            "reason": f"操作 {action} 需要人工审批",
        }

    if action in WARN_ACTIONS:
        _log_audit(task_id, stage_id, action, role, "auto_approved_with_warning", "")
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
        _pending_approvals[approval.id] = approval
        return {
            "level": GuardrailLevel.REQUIRE_REVIEW,
            "proceed": False,
            "approval_id": approval.id,
            "reason": f"阶段 {stage_id} 需要人工审批后继续",
        }

    _log_audit(task_id, stage_id, action, role, "auto_approved", "")
    return {"level": GuardrailLevel.AUTO_APPROVE, "proceed": True}


def resolve_approval(
    approval_id: str,
    approved: bool,
    reviewer: str,
    comment: str = "",
) -> Optional[ApprovalRequest]:
    """Approve or reject a pending approval request."""
    approval = _pending_approvals.get(approval_id)
    if not approval:
        return None

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.reviewer = reviewer
    approval.review_comment = comment
    approval.resolved_at = datetime.utcnow().isoformat()

    outcome = "approved" if approved else "rejected"
    _log_audit(
        approval.task_id, approval.stage_id, approval.action,
        reviewer, outcome, comment,
    )

    return approval


def get_pending_approvals(task_id: Optional[str] = None) -> List[ApprovalRequest]:
    """Get all pending approval requests, optionally filtered by task."""
    approvals = [a for a in _pending_approvals.values() if a.status == ApprovalStatus.PENDING]
    if task_id:
        approvals = [a for a in approvals if a.task_id == task_id]
    return approvals


def get_audit_log(
    task_id: Optional[str] = None,
    limit: int = 100,
) -> List[AuditEntry]:
    """Get audit log entries."""
    entries = _audit_log
    if task_id:
        entries = [e for e in entries if e.task_id == task_id]
    return entries[-limit:]


def _log_audit(
    task_id: str,
    stage_id: str,
    action: str,
    actor: str,
    outcome: str,
    details: str,
) -> None:
    entry = AuditEntry(
        task_id=task_id,
        stage_id=stage_id,
        action=action,
        actor=actor,
        risk_level=GuardrailLevel.WARN.value if action in WARN_ACTIONS else GuardrailLevel.AUTO_APPROVE.value,
        outcome=outcome,
        details=details,
    )
    _audit_log.append(entry)
    if len(_audit_log) > 10000:
        _audit_log[:] = _audit_log[-5000:]
    logger.info(f"[guardrail] {outcome}: {action} by {actor} on task={task_id}/{stage_id}")
