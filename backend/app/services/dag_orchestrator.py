"""
DAG Orchestrator — dependency-based pipeline execution.

Replaces the fixed linear pipeline with a DAG (Directed Acyclic Graph)
where stages can:
- Run in parallel when they share no dependencies
- Be skipped for simple tasks
- Support dynamic stage insertion
- Allow conditional branching (e.g. REJECTED → go back)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import async_session
from ..models.pipeline import PipelineTask, PipelineStage, PipelineArtifact
from .pipeline_engine import execute_stage
from .sse import emit_event
from .observability import start_trace, complete_trace

logger = logging.getLogger(__name__)


# Cap concurrent stages within a single DAG batch. Tunable per deploy via
# DAG_PARALLEL_LIMIT. Keep modest by default — LLM provider rate limits and
# Postgres pool size are usually the binding constraints, not CPU.
_DAG_PARALLEL_LIMIT = max(1, int(os.getenv("DAG_PARALLEL_LIMIT", "4")))


class StageStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class DAGStage:
    """A single stage in the execution DAG.

    Wave-4 fields (``max_retries``, ``on_failure``, ``human_gate``) are
    declarative metadata that mirror the per-stage columns in
    ``pipeline_stages`` and are honoured by ``execute_dag_pipeline``:

    * ``max_retries`` — re-run a failed stage up to N times before
      applying ``on_failure``. Default 0 = no auto-retry.
    * ``on_failure`` — what to do when retries are exhausted.
      ``"halt"`` (default), ``"rollback"``, or ``"skip"``.
    * ``human_gate`` — when True, the stage pauses the DAG after
      completing successfully (status ``awaiting_approval``) until a
      reviewer approves via ``POST /pipeline/tasks/{id}/stages/{sid}/approve``.
    """

    def __init__(
        self,
        stage_id: str,
        label: str,
        role: str,
        depends_on: Optional[List[str]] = None,
        skip_condition: Optional[str] = None,
        *,
        max_retries: int = 0,
        on_failure: str = "halt",
        human_gate: bool = False,
    ):
        self.stage_id = stage_id
        self.label = label
        self.role = role
        self.depends_on = depends_on or []
        self.skip_condition = skip_condition
        self.status = StageStatus.PENDING
        self.output: Optional[str] = None
        self.error: Optional[str] = None
        self.max_retries = int(max_retries)
        self.on_failure = on_failure if on_failure in ("halt", "rollback", "skip") else "halt"
        self.human_gate = bool(human_gate)
        self.retry_count = 0
        # Self-healing: when a downstream reviewer REJECT_TOs back to
        # this stage, the orchestrator stuffs the reviewer's verbatim
        # rejection text here. ``execute_stage`` reads it and prepends
        # it as a "previous-rejection" patch to the system prompt of
        # the next attempt, so the agent sees *why* it was sent back
        # instead of just rerunning the same prompt blind.
        self.reject_feedback: Optional[str] = None
        self.reject_count: int = 0


PIPELINE_TEMPLATES: Dict[str, List[DAGStage]] = {
    "full": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning", "design"]),
        DAGStage("development", "开发实现", "developer", depends_on=["architecture", "design"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "审查验收", "acceptance", depends_on=["testing"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"]),
    ],
    "parallel_design": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "开发实现", "developer", depends_on=["design", "architecture"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "审查验收", "acceptance", depends_on=["testing"]),
    ],
    "simple": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("development", "开发实现", "developer", depends_on=["planning"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
    ],
    "review_only": [
        DAGStage("testing", "测试验证", "qa-lead"),
        DAGStage("reviewing", "审查验收", "acceptance", depends_on=["testing"]),
    ],
    "adaptive": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"], skip_condition="simple_task"),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"], skip_condition="simple_task"),
        DAGStage("development", "开发实现", "developer", depends_on=["planning"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "审查验收", "acceptance", depends_on=["testing"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"], skip_condition="approved"),
    ],
    "web_app": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "界面 & 组件设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "前后端开发", "developer", depends_on=["design", "architecture"]),
        DAGStage("testing", "端到端测试", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "产品验收", "acceptance", depends_on=["testing"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"]),
    ],
    "api_service": [
        DAGStage("planning", "API 需求设计", "product-manager"),
        DAGStage("architecture", "接口 & 数据模型", "architect", depends_on=["planning"]),
        DAGStage("development", "API 实现", "developer", depends_on=["architecture"]),
        DAGStage("testing", "接口测试 & 安全审查", "qa-lead", depends_on=["development"]),
        DAGStage("deployment", "部署 & 文档", "devops", depends_on=["testing"]),
    ],
    "data_pipeline": [
        DAGStage("planning", "数据需求分析", "product-manager"),
        DAGStage("architecture", "数据架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "ETL / 管道开发", "developer", depends_on=["architecture"]),
        DAGStage("testing", "数据质量验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "数据治理审查", "acceptance", depends_on=["testing"]),
    ],
    "bug_fix": [
        DAGStage("planning", "问题分析 & 定位", "product-manager"),
        DAGStage("development", "修复实现", "developer", depends_on=["planning"]),
        DAGStage("testing", "回归测试", "qa-lead", depends_on=["development"]),
    ],
    "microservice": [
        DAGStage("planning", "服务需求 & 边界定义", "product-manager"),
        DAGStage("architecture", "服务架构 & API 契约", "architect", depends_on=["planning"]),
        DAGStage("development", "服务实现", "developer", depends_on=["architecture"]),
        DAGStage("testing", "单元 + 集成 + 契约测试", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "服务验收", "acceptance", depends_on=["testing"]),
        DAGStage("deployment", "容器化部署", "devops", depends_on=["reviewing"]),
    ],
    "fullstack_saas": [
        DAGStage("planning", "产品需求 & 商业模式", "product-manager"),
        DAGStage("design", "界面 & 组件设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "全栈架构 & 技术选型", "architect", depends_on=["planning"]),
        DAGStage("development", "前后端实现", "developer", depends_on=["design", "architecture"]),
        DAGStage("testing", "全链路测试", "qa-lead", depends_on=["development"]),
        DAGStage("security-review", "安全审计", "security", depends_on=["development"]),
        DAGStage("reviewing", "产品验收", "acceptance", depends_on=["testing", "security-review"]),
        DAGStage("deployment", "云端部署 & CI/CD", "devops", depends_on=["reviewing"]),
    ],
    "mobile_app": [
        DAGStage("planning", "移动端需求分析", "product-manager"),
        DAGStage("design", "移动端 UI 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "移动架构 & API", "architect", depends_on=["planning"]),
        DAGStage("development", "移动端开发", "developer", depends_on=["design", "architecture"]),
        DAGStage("testing", "多设备测试 & 性能", "qa-lead", depends_on=["development"]),
        DAGStage("security-review", "安全审计", "security", depends_on=["development"]),
        DAGStage("reviewing", "App 验收", "acceptance", depends_on=["testing", "security-review"]),
        DAGStage("deployment", "商店发布 & 灰度", "devops", depends_on=["reviewing"]),
    ],
    # —— 新增: Enterprise / Growth / Fintech 模板，把孤儿 agent 接进来 —— #
    "enterprise": [
        # 全角色阵容：planning → design + arch → dev → testing/security/legal 并发 →
        # acceptance → deployment。适合 to-B 严格合规场景。
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "开发实现", "developer", depends_on=["design", "architecture"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("security-review", "安全审计", "security", depends_on=["development"]),
        DAGStage("legal-review", "合规审查", "legal", depends_on=["planning", "architecture"]),
        DAGStage("reviewing", "最终验收", "acceptance",
                 depends_on=["testing", "security-review", "legal-review"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"]),
    ],
    "growth_product": [
        # 增长向：在常规链路里追加 data-modeling + marketing-launch。
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("data-modeling", "指标与埋点设计", "data", depends_on=["planning", "design"]),
        DAGStage("development", "开发实现", "developer",
                 depends_on=["design", "architecture", "data-modeling"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "产品验收", "acceptance", depends_on=["testing"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"]),
        DAGStage("marketing-launch", "上线营销包", "marketing",
                 depends_on=["reviewing"]),
    ],
    "fintech": [
        # 金融/支付：security + legal + finance 全部强制，acceptance 收口。
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("design", "UI/UX 设计", "designer", depends_on=["planning"]),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("finance-review", "商业可持续性评估", "finance",
                 depends_on=["planning", "architecture"]),
        DAGStage("development", "开发实现", "developer",
                 depends_on=["design", "architecture", "finance-review"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("security-review", "安全审计", "security", depends_on=["development"]),
        DAGStage("legal-review", "合规审查", "legal",
                 depends_on=["planning", "architecture", "security-review"]),
        DAGStage("reviewing", "最终验收", "acceptance",
                 depends_on=["testing", "security-review", "legal-review"]),
        DAGStage("deployment", "灰度部署", "devops", depends_on=["reviewing"]),
    ],
}

TEMPLATE_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "full": {"label": "完整 SDLC", "description": "规划→架构→开发→测试→验收→部署，适用于中大型项目", "icon": "🏗️"},
    "web_app": {"label": "Web 应用", "description": "前后端一体化开发，含端到端测试和部署", "icon": "🌐"},
    "api_service": {"label": "API 服务", "description": "接口设计→实现→安全测试→部署文档", "icon": "🔌"},
    "data_pipeline": {"label": "数据管道", "description": "数据需求→架构→ETL 开发→质量验证→治理审查", "icon": "📊"},
    "bug_fix": {"label": "Bug 修复", "description": "问题定位→修复→回归测试，快速迭代", "icon": "🐛"},
    "simple": {"label": "极简流程", "description": "规划→开发→测试，适用于小需求", "icon": "⚡"},
    "adaptive": {"label": "自适应", "description": "根据复杂度自动跳过架构/部署阶段", "icon": "🤖"},
    "parallel_design": {"label": "并行设计", "description": "架构与开发可并行执行，加速交付", "icon": "⚡"},
    "review_only": {"label": "仅审查", "description": "跳过开发，仅测试+验收", "icon": "🔍"},
    "microservice": {"label": "微服务", "description": "服务边界→API 契约→实现→契约测试→容器化", "icon": "🔗"},
    "fullstack_saas": {"label": "全栈 SaaS", "description": "完整 SaaS 产品开发：需求→全栈→测试→安全审查→云部署", "icon": "☁️"},
    "mobile_app": {"label": "移动应用", "description": "移动端产品：需求→UI 架构→开发→多设备测试→商店发布", "icon": "📱"},
    "enterprise": {"label": "企业级 / 严格合规", "description": "to-B 全角色阵容：design + 安全审计 + 法务合规 + 验收 + 部署", "icon": "🏛️"},
    "growth_product": {"label": "增长型产品", "description": "在常规链路上追加数据指标设计与上线营销包", "icon": "📈"},
    "fintech": {"label": "金融 / 支付", "description": "金融级合规：财务评估 + 安全审计 + 法务审查 + 灰度部署", "icon": "💳"},
}


def _dag_stages_from_custom_spec(spec: List[Dict[str, Any]]) -> List[DAGStage]:
    """Build a list of ``DAGStage`` from the Workflow Builder JSON spec.

    Mirrors ``BackendStage`` from ``src/services/workflowBuilder.ts``:
    every entry MUST carry ``stage_id`` / ``label`` / ``role``; everything
    else is optional and falls back to the same defaults
    ``PIPELINE_TEMPLATES`` would have used.

    Unknown fields are tolerated (forward-compatible with future builder
    flags). Bad ``on_failure`` strings collapse to ``"halt"`` via the
    ``DAGStage`` constructor itself.
    """
    out: List[DAGStage] = []
    for raw in spec or []:
        if not isinstance(raw, dict):
            continue
        sid = (raw.get("stage_id") or raw.get("stageId") or "").strip()
        label = raw.get("label") or sid
        role = raw.get("role") or raw.get("owner_role") or "developer"
        if not sid:
            # Silently drop ill-formed entries — better than 500-ing the
            # entire run because of a rogue node from an old export.
            continue
        depends_on = raw.get("depends_on") or raw.get("dependsOn") or []
        out.append(
            DAGStage(
                stage_id=sid,
                label=label,
                role=role,
                depends_on=[str(d) for d in depends_on if d],
                skip_condition=raw.get("skip_condition") or raw.get("skipCondition"),
                max_retries=int(raw.get("max_retries") or raw.get("maxRetries") or 0),
                on_failure=str(raw.get("on_failure") or raw.get("onFailure") or "halt"),
                human_gate=bool(raw.get("human_gate") or raw.get("humanGate") or False),
            )
        )
    return out


def get_ready_stages(stages: List[DAGStage], outputs: Dict[str, str] = None) -> List[DAGStage]:
    """Find all stages whose dependencies are satisfied and can run now.
    
    Evaluates skip_condition against collected outputs — stages that match
    their skip predicate are marked SKIPPED rather than returned as ready.
    """
    completed = {s.stage_id for s in stages if s.status in (StageStatus.DONE, StageStatus.SKIPPED)}
    ready = []
    for s in stages:
        if s.status != StageStatus.PENDING:
            continue
        if not all(dep in completed for dep in s.depends_on):
            continue
        if s.skip_condition and _should_skip(s.skip_condition, outputs or {}):
            s.status = StageStatus.SKIPPED
            continue
        ready.append(s)
    return ready


def _should_skip(condition: str, outputs: Dict[str, str]) -> bool:
    """Evaluate a simple skip condition against pipeline outputs.

    Supported conditions:
    - "simple_task": skip if planning output is short (< 500 chars)
    - "no_code": skip if development output contains no code blocks
    - "approved": skip if reviewing output contains APPROVED
    - Custom: "stage.{id}.contains:{text}" pattern
    """
    if condition == "simple_task":
        return len(outputs.get("planning", "")) < 500

    if condition == "no_code":
        return "```" not in outputs.get("development", "")

    if condition == "approved":
        return "APPROVED" in outputs.get("reviewing", "")

    if condition.startswith("stage."):
        parts = condition.split(".", 2)
        if len(parts) == 3 and ".contains:" in parts[2]:
            stage_id = parts[1]
            text = parts[2].split("contains:", 1)[1]
            return text in outputs.get(stage_id, "")

    return False


def _extract_rejection_target(content: str) -> Optional[str]:
    """Extract target stage from rejection content.

    Honors the explicit ``REJECT_TO: <stage_id>`` marker emitted by the
    acceptance-agent first; falls back to fuzzy keyword scan.
    """
    import re
    explicit = re.search(r"REJECT_TO\s*[:：]\s*([\w\-]+)", content, re.IGNORECASE)
    if explicit:
        return explicit.group(1).lower()
    for stage_id in (
        "planning", "design", "architecture", "development", "testing",
        "security-review", "legal-review", "data-modeling",
    ):
        match = re.search(rf'(返回|back to|重新|redo)\s*{stage_id}', content, re.IGNORECASE)
        if match:
            return stage_id
    return "planning"


async def _persist_stage_state(
    db: AsyncSession,
    task_id: str,
    stage: "DAGStage",
    *,
    db_status: Optional[str] = None,
) -> None:
    """Mirror in-memory DAG state to the matching ``pipeline_stages`` row.

    Lets the UI / approve API observe retry counts, last_error, and the
    ``awaiting_approval`` status without waiting for end-of-pipeline sync.
    Best-effort: failures are logged and swallowed.
    """
    try:
        result = await db.execute(
            select(PipelineStage).where(
                PipelineStage.task_id == uuid.UUID(task_id),
                PipelineStage.stage_id == stage.stage_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        if db_status:
            row.status = db_status
        row.retry_count = stage.retry_count
        row.last_error = (stage.error or "")[:5000] if stage.error else None
        await db.flush()
    except Exception as e:
        logger.debug(f"[dag] persist_stage_state failed for {stage.stage_id}: {e}")


def _reset_to_stage(
    stages: List[DAGStage],
    target_stage_id: str,
    *,
    feedback: Optional[str] = None,
) -> None:
    """Reset a stage and all stages that depend on it back to PENDING.

    When ``feedback`` is provided (typical case: reviewer's rejection
    text), it's stamped onto the target stage so the next iteration
    of ``execute_stage`` can inject it as a self-healing prompt
    patch. ``reject_count`` is also incremented so the agent (and
    operators in the UI) can see how many times this stage has been
    bounced back.
    """
    target_idx = next(
        (i for i, s in enumerate(stages) if s.stage_id == target_stage_id), -1,
    )
    if target_idx < 0:
        return

    reset_ids: Set[str] = set()
    for s in stages[target_idx:]:
        if s.stage_id == target_stage_id or any(dep in reset_ids for dep in s.depends_on):
            reset_ids.add(s.stage_id)
            if s.stage_id != "reviewing":
                s.status = StageStatus.PENDING
                s.output = None
                s.error = None

    if feedback:
        target_stage = stages[target_idx]
        target_stage.reject_feedback = feedback
        target_stage.reject_count += 1


def _extract_rejection_feedback(content: str) -> Optional[str]:
    """Pull the human-readable "why" out of a reviewer's verdict.

    The acceptance agent's contract is to emit either::

        REJECTED
        REJECT_TO: development
        REASON:
        <free-form why>

    or any block whose first line says REJECTED — in that case the
    rest of the message *is* the reason. We trim aggressively (8KB
    cap) so a malformed reviewer doesn't fill the next prompt with
    its entire chain-of-thought.
    """
    if not content:
        return None
    import re
    m = re.search(
        r"REASON\s*[:：]\s*(.+)",
        content, re.IGNORECASE | re.DOTALL,
    )
    if m:
        text = m.group(1).strip()
    else:
        # Fall back to "everything after REJECTED" if no explicit REASON.
        idx = content.upper().find("REJECTED")
        text = (content[idx + len("REJECTED"):].strip() if idx >= 0 else content.strip())
    if not text:
        return None
    return text[:8000]


async def _maybe_escalate_after_reject(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    target: str,
    reject_count: int,
) -> None:
    """Throttled escalation: after N rejects on the same stage,
    label the linked issues + ping IM. Lazy-imports the escalation
    module so plain DAG unit tests don't pull in httpx / notify.

    The fan-out itself is internally idempotent (per-process
    high-water-mark on ``reject_count``); we still re-fetch the task
    to read the latest ``external_links`` (admin may have just
    bound a new tracker mid-run).
    """
    try:
        from .escalation import maybe_escalate
    except Exception as exc:  # pragma: no cover - escalation always present
        logger.debug("[dag] escalation skipped (no module): %s", exc)
        return

    task_row = await db.get(PipelineTask, uuid.UUID(task_id))
    links = list(getattr(task_row, "external_links", None) or []) if task_row else []

    summary = await maybe_escalate(
        db,
        task_id=task_id,
        task_title=task_title,
        target_stage=target,
        reject_count=reject_count,
        links=links,
    )
    if summary is not None:
        await emit_event("integrations:escalated", summary)


async def _mirror_reject_to_external_links(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    target: str,
    feedback: Optional[str],
    reject_count: int,
) -> None:
    """Post a comment to every external issue linked to ``task_id``
    summarizing the REJECT verdict.

    Lazy-imports ``mirror_comment_to_links`` and the PipelineTask model
    to avoid pulling httpx into pure-DAG unit tests; if either import
    or the per-link call fails we log + return, never bubbling.

    The comment body is plain text on purpose — Jira's ADF wrapper
    and GitHub Markdown both render it acceptably without escaping.
    """
    try:
        from .connectors import mirror_comment_to_links  # local import
    except Exception as exc:  # pragma: no cover - connectors always present in app
        logger.debug("[dag] mirror skipped (no connectors module): %s", exc)
        return

    # Re-fetch the task so we always see the latest external_links —
    # an admin may have just bound a new issue while the DAG was running.
    task_row = await db.get(PipelineTask, uuid.UUID(task_id))
    if task_row is None:
        return
    links = getattr(task_row, "external_links", None) or []
    if not links:
        return

    preview = (feedback or "(no reason provided)").strip()
    if len(preview) > 1500:
        preview = preview[:1500].rstrip() + "…"

    body = (
        f"[Agent Hub] 评审驳回 → 已自动回到阶段 `{target}`（第 {reject_count} 次返工）\n\n"
        f"**任务**: {task_title}\n"
        f"**Task ID**: {task_id}\n\n"
        f"**驳回理由**:\n{preview}"
    )

    results = await mirror_comment_to_links(links, body)
    # Surface a compact SSE so the UI can show "mirrored to N trackers".
    posted = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = sum(1 for r in results if not r.get("ok") and not r.get("skipped"))
    if results:
        await emit_event("integrations:mirrored", {
            "taskId": task_id, "trigger": "reject",
            "target": target, "rejectCount": reject_count,
            "posted": posted, "skipped": skipped, "failed": failed,
            "results": results,
        })


def resolve_execution_plan(stages: List[DAGStage], outputs: Dict[str, str] = None) -> List[List[DAGStage]]:
    """Resolve the full execution order as batches of parallel-safe stages.
    
    Evaluates skip_condition for each candidate stage so skipped stages
    are excluded from batches and their dependents can still proceed.
    """
    batches: List[List[DAGStage]] = []
    completed: Set[str] = set()
    skipped: Set[str] = set()
    remaining = [s for s in stages if s.status == StageStatus.PENDING]
    effective_outputs = outputs or {}

    while remaining:
        batch = []
        newly_skipped = []
        for s in remaining:
            if not all(dep in completed | skipped for dep in s.depends_on):
                continue
            if s.skip_condition and _should_skip(s.skip_condition, effective_outputs):
                s.status = StageStatus.SKIPPED
                newly_skipped.append(s)
                continue
            batch.append(s)

        for s in newly_skipped:
            skipped.add(s.stage_id)

        if not batch and not newly_skipped:
            for s in remaining:
                s.status = StageStatus.BLOCKED
            batches.append(remaining)
            break

        if batch:
            batches.append(batch)
        for s in batch:
            completed.add(s.stage_id)
        remaining = [s for s in remaining if s.stage_id not in completed and s.stage_id not in skipped]

    return batches


async def execute_dag_pipeline(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    template: str = "full",
    complexity: Optional[str] = None,
    project_path: Optional[str] = None,
    resume: bool = False,
    custom_stages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Execute a pipeline using DAG-based scheduling.

    Stages without dependencies run in parallel.

    If `resume=True` and a checkpoint exists for this task, stages already
    marked DONE are skipped (their outputs are restored), and the run picks
    up from the first non-DONE stage.

    When ``custom_stages`` is provided (typically when ``template=="custom"``)
    it takes precedence over ``PIPELINE_TEMPLATES[template]``. The shape
    matches ``BackendStage`` from the Workflow Builder UI — see
    ``_dag_stages_from_custom_spec`` for the field-by-field mapping.
    """
    if custom_stages:
        template_stages = _dag_stages_from_custom_spec(custom_stages)
    else:
        template_stages = PIPELINE_TEMPLATES.get(template, PIPELINE_TEMPLATES["full"])
    stages = [
        DAGStage(
            s.stage_id, s.label, s.role,
            list(s.depends_on), s.skip_condition,
            max_retries=getattr(s, "max_retries", 0),
            on_failure=getattr(s, "on_failure", "halt"),
            human_gate=getattr(s, "human_gate", False),
        )
        for s in template_stages
    ]

    # When the matching DB row exists with overrides, prefer those — lets
    # operators tweak retry/gate per-task without redeploying.
    db_stage_overrides: Dict[str, Dict[str, Any]] = {}
    try:
        result = await db.execute(
            select(PipelineStage).where(PipelineStage.task_id == uuid.UUID(task_id))
        )
        for row in result.scalars().all():
            db_stage_overrides[row.stage_id] = {
                "max_retries": int(row.max_retries or 0),
                "on_failure": row.on_failure or "halt",
                "human_gate": bool(row.human_gate),
                "retry_count": int(row.retry_count or 0),
            }
    except Exception as e:
        logger.debug(f"[dag] no per-stage overrides loaded: {e}")
    for stg in stages:
        ov = db_stage_overrides.get(stg.stage_id)
        if not ov:
            continue
        if ov["max_retries"]:
            stg.max_retries = ov["max_retries"]
        if ov["on_failure"]:
            stg.on_failure = ov["on_failure"]
        stg.human_gate = stg.human_gate or ov["human_gate"]
        stg.retry_count = ov["retry_count"]

    from .pipeline_checkpoint import load_checkpoint, save_checkpoint
    outputs: Dict[str, str] = {}
    resumed_from = None
    if resume:
        ckpt = await load_checkpoint(db, task_id)
        saved_outputs: Dict[str, str] = (ckpt or {}).get("outputs") or {}
        saved_states = {
            s.get("stage_id"): s
            for s in ((ckpt or {}).get("stage_states") or [])
            if isinstance(s, dict)
        }

        # Merge live DB state — covers the case where the user approved a
        # human-gate stage (or manually edited a row) after the last
        # checkpoint was written.
        try:
            db_rows = await db.execute(
                select(PipelineStage).where(PipelineStage.task_id == uuid.UUID(task_id))
            )
            for row in db_rows.scalars().all():
                if row.status == "done" and row.output:
                    saved_outputs.setdefault(row.stage_id, row.output)
                    saved_states.setdefault(
                        row.stage_id,
                        {"stage_id": row.stage_id, "status": StageStatus.DONE.value},
                    )
        except Exception as e:
            logger.debug(f"[dag] resume: could not merge DB state: {e}")

        for stg in stages:
            state = saved_states.get(stg.stage_id) or {}
            if state.get("status") == StageStatus.DONE.value and saved_outputs.get(stg.stage_id):
                stg.status = StageStatus.DONE
                stg.output = saved_outputs[stg.stage_id]
                outputs[stg.stage_id] = stg.output
        resumed_from = next(
            (s.stage_id for s in stages if s.status != StageStatus.DONE),
            None,
        )

    trace = await start_trace(task_id, task_title)
    await emit_event("pipeline:dag-start", {
        "taskId": task_id, "title": task_title,
        "template": template, "stageCount": len(stages),
        "resumed": bool(resume and resumed_from),
        "resumedFrom": resumed_from,
        "skippedStages": [s.stage_id for s in stages if s.status == StageStatus.DONE],
    })

    results: List[Dict[str, Any]] = []
    max_iterations = len(stages) * 2  # cap to prevent infinite rejection loops
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        ready = get_ready_stages(stages, outputs)
        if not ready:
            break

        batch_idx = iteration - 1
        await emit_event("pipeline:dag-batch", {
            "taskId": task_id, "batchIndex": batch_idx,
            "stageIds": [s.stage_id for s in ready],
        })

        async def _run_stage(stage: DAGStage, stage_db: AsyncSession) -> Dict[str, Any]:
            stage.status = StageStatus.RUNNING
            await emit_event("stage:processing", {
                "taskId": task_id, "stageId": stage.stage_id,
                "label": stage.label, "role": stage.role,
            })

            stage_result = await execute_stage(
                stage_db,
                task_id=task_id,
                task_title=task_title,
                task_description=task_description,
                stage_id=stage.stage_id,
                previous_outputs=outputs,
                trace=trace,
                complexity=complexity,
                template=template,
                project_path=project_path,
                reject_feedback=stage.reject_feedback,
                reject_count=stage.reject_count,
            )
            # One-shot consumption: clear the feedback after the agent
            # has seen it, so a subsequent retry-without-rejection
            # (e.g. a transient LLM error) doesn't keep replaying old
            # criticism that the agent has already addressed.
            stage.reject_feedback = None

            if stage_result.get("ok"):
                stage.status = StageStatus.DONE
                stage.output = stage_result.get("content", "")
                outputs[stage.stage_id] = stage.output

                # --- Quality Gate Evaluation (DAG path) ---
                try:
                    from .quality_gates import evaluate_quality_gate
                    from .self_verify import StageVerification, VerifyStatus, VerifyResult

                    verification = stage_result.get("verification", {})
                    heuristic = StageVerification(
                        stage_id=stage.stage_id, role="",
                        overall_status=VerifyStatus(verification.get("status", "pass")),
                        checks=[
                            VerifyResult(
                                check_name=c.get("check_name", c.get("name", "")),
                                status=VerifyStatus(c.get("status", "pass")),
                                message=c.get("message", ""),
                            )
                            for c in verification.get("checks", [])
                        ],
                        auto_proceed=verification.get("auto_proceed", True),
                    )
                    gate_result = await evaluate_quality_gate(
                        stage.stage_id, stage.output,
                        template=template,
                        previous_outputs=outputs,
                        heuristic_result=heuristic,
                        skip_llm=False,
                    )

                    db_result_inner = await stage_db.execute(
                        select(PipelineStage).where(
                            PipelineStage.task_id == uuid.UUID(task_id),
                            PipelineStage.stage_id == stage.stage_id,
                        )
                    )
                    db_stage = db_result_inner.scalar_one_or_none()
                    if db_stage:
                        db_stage.gate_status = gate_result.overall_status.value
                        db_stage.gate_score = gate_result.overall_score
                        db_stage.gate_details = {
                            "checks": [c.dict() for c in gate_result.checks],
                            "suggestions": gate_result.suggestions,
                            "block_reason": gate_result.block_reason,
                        }
                        await stage_db.flush()

                    await emit_event("stage:quality-gate", {
                        "taskId": task_id,
                        "stageId": stage.stage_id,
                        "gateStatus": gate_result.overall_status.value,
                        "gateScore": gate_result.overall_score,
                        "canProceed": gate_result.can_proceed,
                        "blockReason": gate_result.block_reason,
                    })

                    if not gate_result.can_proceed:
                        stage.status = StageStatus.BLOCKED
                        stage.error = f"Quality gate failed: {gate_result.block_reason or 'score too low'}"
                        stage_result["ok"] = False
                        stage_result["gate_blocked"] = True
                        stage_result["gate_result"] = gate_result.dict()
                        await emit_event("pipeline:auto-paused", {
                            "taskId": task_id,
                            "stoppedAt": stage.stage_id,
                            "reason": f"质量门禁未通过: {gate_result.block_reason or '评分过低'}",
                            "gateScore": gate_result.overall_score,
                        })
                except Exception as gate_err:
                    logger.warning(f"[dag] Quality gate evaluation failed for {stage.stage_id}: {gate_err}")

                if stage.status == StageStatus.DONE:
                    await emit_event("stage:completed", {
                        "taskId": task_id, "stageId": stage.stage_id,
                    })

                if stage.stage_id == "reviewing" and "REJECTED" in stage.output:
                    target = _extract_rejection_target(stage.output)
                    if target:
                        feedback = _extract_rejection_feedback(stage.output)
                        _reset_to_stage(stages, target, feedback=feedback)
                        # Find the actual target stage so we can surface
                        # the per-stage reject_count in the SSE event.
                        target_stage = next(
                            (s for s in stages if s.stage_id == target), None,
                        )
                        reject_count = target_stage.reject_count if target_stage else 0
                        await emit_event("pipeline:dag-branch", {
                            "taskId": task_id, "from": "reviewing", "to": target,
                            "reason": "Review rejected, returning to earlier stage",
                            "feedbackPreview": (feedback or "")[:200],
                            "rejectCount": reject_count,
                        })

                        # ── Bidirectional mirror to external trackers ──
                        # If the task is linked to one or more Jira /
                        # GitHub issues (PipelineTask.external_links),
                        # post a comment so reviewers see the AI's
                        # verdict in their own queue. Failures are
                        # swallowed inside the mirror — never block the
                        # DAG on a flaky external service.
                        try:
                            await _mirror_reject_to_external_links(
                                stage_db,
                                task_id=task_id,
                                task_title=task_title,
                                target=target,
                                feedback=feedback,
                                reject_count=reject_count,
                            )
                        except Exception as mirror_err:  # pragma: no cover - defensive
                            logger.warning(
                                "[dag] external-link mirror failed for %s: %s",
                                task_id, mirror_err,
                            )

                        # ── Escalation throttle ──────────────────
                        # After N (default 3) rejects on the same
                        # stage, add a "needs human" label, post a
                        # louder comment, and ping IM. Throttled
                        # internally so retry storms don't re-spam.
                        try:
                            await _maybe_escalate_after_reject(
                                stage_db,
                                task_id=task_id,
                                task_title=task_title,
                                target=target,
                                reject_count=reject_count,
                            )
                        except Exception as esc_err:  # pragma: no cover - defensive
                            logger.warning(
                                "[dag] escalation failed for %s: %s",
                                task_id, esc_err,
                            )

                # ── Wave 4: human approval gate ──────────────────────
                # When the stage definition (or DB override) marks
                # `human_gate=True`, pause the DAG after success. The
                # frontend / API can flip the stage back to DONE via the
                # existing /approve endpoint and then call /resume-dag.
                if stage.status == StageStatus.DONE and stage.human_gate:
                    stage.status = StageStatus.BLOCKED  # treated as paused
                    stage_result["ok"] = False  # so the outer loop breaks
                    stage_result["awaiting_approval"] = True
                    await _persist_stage_state(
                        stage_db, task_id, stage,
                        db_status="awaiting_approval",
                    )
                    await emit_event("stage:awaiting-approval", {
                        "taskId": task_id, "stageId": stage.stage_id,
                        "label": stage.label, "role": stage.role,
                        "reason": "human_gate",
                    })
            else:
                # ── Wave 4: retry budget + on_failure policy ────────
                err = stage_result.get("error", "Unknown error")
                stage.error = err

                # Auto-retry within budget (in-process, same iteration).
                if stage.retry_count < stage.max_retries:
                    stage.retry_count += 1
                    await _persist_stage_state(
                        stage_db, task_id, stage, db_status="active",
                    )
                    await emit_event("stage:retry", {
                        "taskId": task_id, "stageId": stage.stage_id,
                        "attempt": stage.retry_count,
                        "maxRetries": stage.max_retries,
                        "lastError": err[:500],
                    })
                    # Recurse once via a tail call — keeps the surrounding
                    # gather logic intact and bounded by max_retries.
                    return await _run_stage(stage, stage_db)

                stage.status = StageStatus.FAILED
                await _persist_stage_state(
                    stage_db, task_id, stage, db_status="error",
                )
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage.stage_id,
                    "error": err,
                    "retryCount": stage.retry_count,
                    "onFailure": stage.on_failure,
                })

                if stage.on_failure == "rollback":
                    # Reset this stage + downstream to PENDING and pause
                    # the pipeline so a human can decide what to do next.
                    _reset_to_stage(stages, stage.stage_id)
                    stage.status = StageStatus.BLOCKED
                    stage_result["ok"] = False
                    stage_result["rollback"] = True
                    await emit_event("pipeline:rollback", {
                        "taskId": task_id, "stageId": stage.stage_id,
                        "from": stage.stage_id,
                        "reason": err[:200],
                    })
                elif stage.on_failure == "skip":
                    stage.status = StageStatus.SKIPPED
                    stage_result["ok"] = True   # let downstream proceed
                    stage_result["skipped_after_failure"] = True
                    await emit_event("stage:skipped", {
                        "taskId": task_id, "stageId": stage.stage_id,
                        "reason": "on_failure=skip after retries exhausted",
                    })
                # else: halt — outer loop sees ok=False and breaks (current behavior)

            return {"stageId": stage.stage_id, **stage_result}

        # ─────────────────────────────────────────────────────────
        # Real parallel dispatch
        #
        # Each parallel stage runs in its OWN AsyncSession (SQLAlchemy
        # AsyncSession is not safe for concurrent use). A semaphore caps
        # in-flight count so we don't blow LLM rate limits or DB pools.
        # The orchestrator's outer `db` is NOT shared with stage workers.
        # ─────────────────────────────────────────────────────────
        sem = asyncio.Semaphore(_DAG_PARALLEL_LIMIT)

        async def _run_stage_isolated(stage: DAGStage) -> Dict[str, Any]:
            """Own session + commit lifecycle per stage."""
            async with sem:
                t0 = time.monotonic()
                async with async_session() as stage_db:
                    try:
                        result = await _run_stage(stage, stage_db)
                        await stage_db.commit()
                    except Exception as exc:
                        await stage_db.rollback()
                        logger.exception(
                            "[dag] isolated stage %s crashed", stage.stage_id,
                        )
                        result = {"stageId": stage.stage_id, "ok": False, "error": str(exc)}
                result["_elapsed_s"] = round(time.monotonic() - t0, 3)
                return result

        if len(ready) == 1:
            # Single-stage batch — keep the cheaper code path that reuses
            # the orchestrator's session (no session-isolation needed).
            result = await _run_stage(ready[0], db)
            results.append(result)
            if not result.get("ok"):
                break
        else:
            batch_t0 = time.monotonic()
            batch_results = await asyncio.gather(
                *[_run_stage_isolated(s) for s in ready],
                return_exceptions=True,
            )
            normalised: List[Dict[str, Any]] = []
            for br in batch_results:
                if isinstance(br, Exception):
                    normalised.append({"ok": False, "error": str(br)})
                else:
                    normalised.append(br)
            results.extend(normalised)

            wall = round(time.monotonic() - batch_t0, 3)
            sequential = round(
                sum(r.get("_elapsed_s", 0.0) for r in normalised if isinstance(r, dict)),
                3,
            )
            speedup = round(sequential / wall, 2) if wall > 0 else None
            await emit_event("pipeline:dag-batch-stats", {
                "taskId": task_id,
                "batchIndex": batch_idx,
                "stageIds": [s.stage_id for s in ready],
                "concurrency": min(len(ready), _DAG_PARALLEL_LIMIT),
                "wallSeconds": wall,
                "serialSeconds": sequential,
                "speedup": speedup,
            })
            logger.info(
                "[dag] batch=%d stages=%s wall=%.2fs serial=%.2fs speedup=%s",
                batch_idx, [s.stage_id for s in ready], wall, sequential, speedup,
            )

            if any(not r.get("ok") for r in normalised if isinstance(r, dict)):
                break

        try:
            await save_checkpoint(
                db,
                task_id=task_id,
                template=template,
                stage_states=[
                    {"stage_id": s.stage_id, "status": s.status.value, "error": s.error}
                    for s in stages
                ],
                outputs=outputs,
                iteration=iteration,
            )
        except Exception as ckpt_err:
            logger.debug(f"[dag] checkpoint save failed: {ckpt_err}")

    all_ok = all(r.get("ok", False) for r in results if isinstance(r, dict))
    blocked_stage = next((s for s in stages if s.status == StageStatus.BLOCKED), None)
    failed_stage = next((s for s in stages if s.status == StageStatus.FAILED), None)
    if blocked_stage:
        await complete_trace(trace.trace_id, status="paused")
    else:
        await complete_trace(trace.trace_id, status="completed" if all_ok else "failed")

    await emit_event("pipeline:dag-completed", {
        "taskId": task_id,
        "stagesCompleted": sum(1 for s in stages if s.status == StageStatus.DONE),
        "stagesTotal": len(stages),
    })

    db_result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    db_task = db_result.scalar_one_or_none()
    if db_task:
        for stage in stages:
            if stage.output:
                db_stage = next(
                    (s for s in db_task.stages if s.stage_id == stage.stage_id), None
                )
                if db_stage:
                    db_stage.output = stage.output
                    if stage.status == StageStatus.DONE:
                        db_stage.status = "done"
                        db_stage.completed_at = datetime.utcnow()
                    elif stage.status == StageStatus.BLOCKED:
                        # Preserve "awaiting_approval" written by the
                        # human-gate hook — don't downgrade it to "blocked".
                        if db_stage.status != "awaiting_approval":
                            db_stage.status = "blocked"
                        db_stage.completed_at = None

                artifact = PipelineArtifact(
                    task_id=db_task.id,
                    artifact_type="document",
                    name=f"{stage.label} 产出",
                    content=stage.output[:50000],
                    stage_id=stage.stage_id,
                )
                db.add(artifact)

        if all_ok:
            db_task.status = "done"
            db_task.current_stage_id = "done"
        elif blocked_stage:
            db_task.status = "paused"
            db_task.current_stage_id = blocked_stage.stage_id
        elif failed_stage:
            db_task.status = "failed"
            db_task.current_stage_id = failed_stage.stage_id
        gate_scores = [
            s.gate_score for s in db_task.stages if s.gate_score is not None
        ]
        if gate_scores:
            db_task.overall_quality_score = round(
                sum(gate_scores) / len(gate_scores), 3
            )
        await db.flush()

    return {
        "ok": all_ok,
        "results": results,
        "traceId": trace.trace_id,
        "template": template,
        "summary": {
            "stagesCompleted": sum(1 for s in stages if s.status == StageStatus.DONE),
            "stagesSkipped": sum(1 for s in stages if s.status == StageStatus.SKIPPED),
            "stagesTotal": len(stages),
        },
    }
