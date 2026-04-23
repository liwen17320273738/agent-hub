"""RCA Reporter — generate structured root-cause reports for failed tasks.

Aggregates evidence from:
  - PipelineTask + PipelineStage (status, last_error, retry_count, owner_role)
  - TraceRecord + SpanRecord (per-stage span errors, durations, models)
  - AuditLog (guardrail decisions, blocked actions)
  - AgentMessage bus (recent inter-agent traffic on the task topic)

Then asks an LLM to synthesize:
  { root_cause, contributing_factors[], recommended_actions[], severity }

The report is returned synchronously (LLM is the slow path). For large
pipelines we cap evidence to the most relevant slices to keep the prompt
under model limits.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.observability import AuditLog, SpanRecord, TraceRecord
from ..models.pipeline import PipelineStage, PipelineTask

logger = logging.getLogger(__name__)

MAX_SPANS = 20
MAX_BUS_MSGS = 15
MAX_AUDIT = 10
MAX_EVIDENCE_CHARS = 6000


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


async def _collect_stage_evidence(
    db: AsyncSession, task: PipelineTask
) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(PipelineStage)
            .where(PipelineStage.task_id == task.id)
            .order_by(PipelineStage.sort_order)
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for s in rows:
        out.append({
            "stage_id": s.stage_id,
            "label": s.label,
            "owner_role": s.owner_role,
            "status": s.status,
            "retry_count": s.retry_count or 0,
            "max_retries": s.max_retries or 0,
            "last_error": _truncate(s.last_error or "", 600),
            "verify_status": s.verify_status,
            "started_at": s.started_at.isoformat() + "Z" if s.started_at else None,
            "completed_at": s.completed_at.isoformat() + "Z" if s.completed_at else None,
            "output_preview": _truncate(s.output or "", 600),
        })
    return out


async def _collect_spans(db: AsyncSession, task_id: str) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(SpanRecord)
            .where(SpanRecord.task_id == str(task_id))
            .order_by(desc(SpanRecord.started_at))
            .limit(MAX_SPANS)
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for sp in rows:
        out.append({
            "stage_id": sp.stage_id,
            "role": sp.role,
            "model": sp.model,
            "status": sp.status,
            "error": _truncate(sp.error or "", 400),
            "duration_ms": sp.duration_ms,
            "total_tokens": sp.total_tokens,
            "retry_count": sp.retry_count,
            "verify_status": sp.verify_status,
        })
    return out


async def _collect_audit(db: AsyncSession, task_id: str) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.task_id == str(task_id))
            .order_by(desc(AuditLog.created_at))
            .limit(MAX_AUDIT)
        )
    ).scalars().all()
    return [
        {
            "stage_id": a.stage_id,
            "action": a.action,
            "actor": a.actor,
            "risk_level": a.risk_level,
            "outcome": a.outcome,
            "details": _truncate(a.details or "", 200),
            "ts": a.created_at.isoformat() + "Z" if a.created_at else None,
        }
        for a in rows
    ]


async def _collect_bus_msgs(db: AsyncSession, task_id: str) -> List[Dict[str, Any]]:
    try:
        from .agent_bus import get_recent
    except Exception:
        return []
    try:
        msgs = await get_recent(db, task_id=str(task_id), limit=MAX_BUS_MSGS)
    except Exception as e:
        logger.warning("agent_bus.get_recent failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for m in msgs:
        try:
            payload = m.get("payload") if isinstance(m, dict) else None
            out.append({
                "topic": m.get("topic") if isinstance(m, dict) else None,
                "sender": m.get("sender") if isinstance(m, dict) else None,
                "ts": m.get("created_at") if isinstance(m, dict) else None,
                "payload": _truncate(json.dumps(payload, ensure_ascii=False)[:400] if payload else "", 400),
            })
        except Exception:
            continue
    return out


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _format_evidence(
    task: PipelineTask,
    stages: List[Dict[str, Any]],
    spans: List[Dict[str, Any]],
    audits: List[Dict[str, Any]],
    bus_msgs: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []
    parts.append(f"# Task\n- ID: {task.id}\n- Title: {task.title}\n- Status: {task.status}\n")
    parts.append("# Stages\n")
    for s in stages:
        parts.append(
            f"- [{s['stage_id']}] role={s['owner_role']} status={s['status']} "
            f"retry={s['retry_count']}/{s['max_retries']} verify={s['verify_status']}"
        )
        if s["last_error"]:
            parts.append(f"  ERROR: {s['last_error']}")
        if s["output_preview"] and s["status"] in {"failed", "blocked"}:
            parts.append(f"  Output preview: {s['output_preview']}")
    if spans:
        parts.append("\n# Recent spans (most recent first)\n")
        for sp in spans:
            parts.append(
                f"- stage={sp['stage_id']} role={sp['role']} model={sp['model']} "
                f"status={sp['status']} dur={sp['duration_ms']}ms tokens={sp['total_tokens']} "
                f"retry={sp['retry_count']}"
                + (f" ERROR={sp['error']}" if sp.get("error") else "")
            )
    if audits:
        parts.append("\n# Audit / guardrail events\n")
        for a in audits:
            parts.append(
                f"- {a['ts']} stage={a['stage_id']} action={a['action']} "
                f"risk={a['risk_level']} outcome={a['outcome']} :: {a['details']}"
            )
    if bus_msgs:
        parts.append("\n# Inter-agent bus messages\n")
        for m in bus_msgs:
            parts.append(
                f"- {m.get('ts')} topic={m.get('topic')} sender={m.get('sender')} :: {m.get('payload')}"
            )
    full = "\n".join(parts)
    return _truncate(full, MAX_EVIDENCE_CHARS)


async def generate_rca(
    db: AsyncSession, *, task_id: str, use_llm: bool = True
) -> Dict[str, Any]:
    task = await db.get(PipelineTask, task_id)
    if not task:
        return {"ok": False, "error": "task not found"}

    stages = await _collect_stage_evidence(db, task)
    spans = await _collect_spans(db, task_id)
    audits = await _collect_audit(db, task_id)
    bus_msgs = await _collect_bus_msgs(db, task_id)

    failed_stages = [s for s in stages if s["status"] in {"failed", "blocked", "awaiting_approval"}]
    has_failure = bool(failed_stages) or task.status in {"failed", "blocked"}
    evidence_text = _format_evidence(task, stages, spans, audits, bus_msgs)

    base = {
        "ok": True,
        "task_id": str(task.id),
        "task_title": task.title,
        "task_status": task.status,
        "has_failure": has_failure,
        "stages": stages,
        "failed_stages": failed_stages,
        "spans_examined": len(spans),
        "audits_examined": len(audits),
        "bus_msgs_examined": len(bus_msgs),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    if not has_failure:
        base.update({
            "summary": "No failure detected; task is progressing or completed.",
            "root_cause": None,
            "contributing_factors": [],
            "recommended_actions": [],
            "severity": "info",
        })
        return base

    if not use_llm:
        first = failed_stages[0] if failed_stages else stages[-1]
        return {
            **base,
            "summary": f"Failure at stage {first['stage_id']} ({first['owner_role']}).",
            "root_cause": first.get("last_error") or "(no recorded error)",
            "contributing_factors": [],
            "recommended_actions": [
                "Inspect stage logs and span errors",
                "Consider increasing max_retries or relaxing the failing tool",
            ],
            "severity": "high",
            "evidence": evidence_text,
        }

    from ..config import settings
    from .llm_router import chat_completion

    sys = (
        "You are a senior SRE / AI agent reliability engineer. Produce a "
        "structured Root Cause Analysis from the evidence below. "
        "Output ONLY a JSON object — no markdown fences. Schema:\n"
        "{\n"
        '  "summary": "1-2 sentence summary",\n'
        '  "root_cause": "the single most likely root cause",\n'
        '  "contributing_factors": ["...", "..."],\n'
        '  "recommended_actions": ["concrete fix 1", "concrete fix 2"],\n'
        '  "severity": "low|medium|high|critical",\n'
        '  "blast_radius": "scope of impact (this task | this agent | platform)"\n'
        "}"
    )
    try:
        rsp = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": evidence_text},
            ],
            temperature=0.1,
        )
    except Exception as e:
        return {**base, "llm_error": f"RCA call failed: {e}", "evidence": evidence_text}

    if not rsp or rsp.get("error"):
        return {**base, "llm_error": rsp.get("error") if rsp else "no rsp", "evidence": evidence_text}

    raw = _strip_fences(rsp.get("content") or "")
    try:
        parsed = json.loads(raw)
    except Exception:
        return {**base, "llm_raw": raw[:1000], "evidence": evidence_text}

    result = {
        **base,
        "summary": str(parsed.get("summary") or "")[:600],
        "root_cause": str(parsed.get("root_cause") or "")[:1000],
        "contributing_factors": [str(x)[:400] for x in (parsed.get("contributing_factors") or [])][:8],
        "recommended_actions": [str(x)[:400] for x in (parsed.get("recommended_actions") or [])][:8],
        "severity": str(parsed.get("severity") or "medium")[:20],
        "blast_radius": str(parsed.get("blast_radius") or "this task")[:60],
        "evidence": evidence_text,
    }

    result["business_card"] = _build_business_card(result, failed_stages)
    return result


def _build_business_card(
    rca: Dict[str, Any],
    failed_stages: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Distill the RCA into 4 human-readable fields for the FailureCard UI."""
    first = failed_stages[0] if failed_stages else {}
    role_name = first.get("owner_role") or "agent"
    label = first.get("label") or first.get("stage_id") or "未知阶段"
    error = first.get("last_error") or ""

    stuck_at = f"{label}（{role_name}）执行时出错"

    reason = rca.get("root_cause") or error or "未知原因"
    if len(reason) > 120:
        reason = reason[:117] + "…"

    owner = _infer_owner(error, role_name)

    actions = rca.get("recommended_actions") or []
    next_step = actions[0] if actions else "检查日志后重试"

    return {
        "stuck_at": stuck_at,
        "reason": reason,
        "owner": owner,
        "next_step": next_step,
        "severity": rca.get("severity", "medium"),
    }


def _infer_owner(error: str, role: str) -> str:
    e = (error or "").lower()
    if any(k in e for k in ("api key", "auth", "401", "403", "credential")):
        return "Admin 需要检查密钥配置"
    if any(k in e for k in ("rate_limit", "429", "quota", "超限")):
        return "Admin 需要调整额度或降级模型"
    if any(k in e for k in ("context_length", "too long", "上下文")):
        return "用户需要精简输入内容"
    if any(k in e for k in ("timeout", "超时", "timed out")):
        return "Agent 可以自动重试"
    return "Agent 可以自动重试"
