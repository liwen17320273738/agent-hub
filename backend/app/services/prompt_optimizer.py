"""Prompt Optimizer — second half of the data loop.

Given an agent and a recent EvalRun (or the most recent run automatically),
analyze the failures, ask an LLM critic to propose a revised system prompt,
and (optionally) apply it.

Pipeline:

  1. `analyze_recent_failures(agent_id)` — pulls last EvalRun for the agent's
     role, returns failed/low-score cases plus aggregate stats.
  2. `propose_revision(agent_id)` — runs an LLM critic with the failures and
     current system_prompt, returns {old_prompt, new_prompt, rationale}.
  3. `apply_revision(agent_id, new_prompt)` — writes the new prompt back to
     AgentDefinition; previous prompt is preserved in capabilities.history.

Apply is gated behind an explicit second call so a human can review the
diff before it lands. The history snapshot lets you roll back.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent import AgentDefinition
from ..models.eval import EvalCase, EvalResult, EvalRun
from .llm_router import chat_completion

logger = logging.getLogger(__name__)

MAX_FAILURES_IN_PROMPT = 6
MAX_OUTPUT_CHARS = 800


async def _latest_run_for_role(db: AsyncSession, role: str) -> Optional[EvalRun]:
    if not role:
        return None
    q = (
        select(EvalRun)
        .where(EvalRun.agent_role_override == role)
        .where(EvalRun.status.in_(["completed", "failed"]))
        .order_by(desc(EvalRun.completed_at), desc(EvalRun.started_at))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()


async def analyze_recent_failures(
    db: AsyncSession,
    *,
    agent_id: str,
    run_id: Optional[str] = None,
    score_threshold: float = 0.7,
) -> Dict[str, Any]:
    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        return {"ok": False, "error": "agent not found"}

    role = agent.pipeline_role or agent.id
    if run_id:
        run = await db.get(EvalRun, run_id)
    else:
        run = await _latest_run_for_role(db, role)
    if not run:
        return {
            "ok": True,
            "agent_id": agent_id,
            "role": role,
            "run_id": None,
            "failures": [],
            "summary": "no recent eval run found for this role",
        }

    res_q = select(EvalResult).where(EvalResult.run_id == run.id)
    results: List[EvalResult] = list((await db.execute(res_q)).scalars().all())

    failures: List[Dict[str, Any]] = []
    for r in results:
        if r.passed and r.score >= score_threshold:
            continue
        case = await db.get(EvalCase, r.case_id) if r.case_id else None
        failures.append({
            "case_id": str(r.case_id) if r.case_id else None,
            "case_name": r.case_name or "",
            "task": (case.task if case else "")[:600],
            "expected": (case.expected if case else {}),
            "scorer": r.scorer,
            "score": float(r.score or 0.0),
            "passed": bool(r.passed),
            "output": (r.output or "")[:MAX_OUTPUT_CHARS],
            "error": (r.error or "")[:300],
            "scorer_detail": r.scorer_detail or {},
        })

    return {
        "ok": True,
        "agent_id": agent_id,
        "role": role,
        "run_id": str(run.id),
        "run_label": run.label,
        "run_avg_score": float(run.avg_score or 0.0),
        "run_passed": run.passed_cases,
        "run_failed": run.failed_cases,
        "failures": failures,
        "summary": (
            f"{len(failures)} failing/low-score cases out of "
            f"{run.total_cases} ({run.passed_cases} passed)"
        ),
    }


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json|markdown|md)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


async def propose_revision(
    db: AsyncSession,
    *,
    agent_id: str,
    run_id: Optional[str] = None,
    score_threshold: float = 0.7,
) -> Dict[str, Any]:
    """Ask an LLM critic to propose a revised system prompt."""
    analysis = await analyze_recent_failures(
        db, agent_id=agent_id, run_id=run_id, score_threshold=score_threshold
    )
    if not analysis.get("ok"):
        return analysis
    failures = analysis["failures"]
    if not failures:
        return {
            "ok": True,
            "agent_id": agent_id,
            "skipped": True,
            "reason": "no failing cases — current prompt looks healthy",
            "old_prompt": (await db.get(AgentDefinition, agent_id)).system_prompt or "",
        }

    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        return {"ok": False, "error": "agent not found"}
    old_prompt = agent.system_prompt or ""

    failure_block = []
    for f in failures[:MAX_FAILURES_IN_PROMPT]:
        failure_block.append(
            f"### Case: {f.get('case_name') or '(unnamed)'}\n"
            f"- Task: {f.get('task','')}\n"
            f"- Expected: {json.dumps(f.get('expected',{}), ensure_ascii=False)[:400]}\n"
            f"- Score: {f.get('score'):.2f}  (passed={f.get('passed')})\n"
            f"- Scorer detail: {json.dumps(f.get('scorer_detail',{}), ensure_ascii=False)[:300]}\n"
            f"- Agent output (truncated):\n{f.get('output','')}\n"
        )

    sys = (
        "You are a senior prompt engineer reviewing a production AI agent that "
        "is failing some evals. You will revise its SYSTEM PROMPT so the "
        "failure cases pass without breaking working behavior. "
        "Output ONLY a JSON object with this exact shape — no markdown fences:\n"
        "{\n"
        '  "new_prompt": "<full revised system prompt, in the agent\'s original language>",\n'
        '  "rationale": "<1-3 paragraphs explaining the diff>",\n'
        '  "diff_summary": ["bullet 1", "bullet 2", "..."]\n'
        "}\n"
        "Rules:\n"
        " - Preserve the agent's identity, role, and any working instructions.\n"
        " - Only ADD constraints / examples / clarifications targeted at the "
        "specific failure modes you see.\n"
        " - Keep the prompt under 4000 characters.\n"
    )
    user = (
        f"# Agent: {agent.title or agent.id}\n"
        f"Role: {agent.pipeline_role or agent.id}\n"
        f"Avg score on last run: {analysis['run_avg_score']:.2f}\n"
        f"Failures: {analysis['run_failed']} / {analysis['run_passed'] + analysis['run_failed']}\n\n"
        f"## Current system prompt\n{old_prompt[:3500]}\n\n"
        f"## Failing cases\n" + "\n".join(failure_block)
    )

    from ..config import settings
    try:
        rsp = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.2,
        )
    except Exception as e:
        return {"ok": False, "error": f"critic call failed: {e}"}
    if not rsp or rsp.get("error"):
        return {"ok": False, "error": rsp.get("error") if rsp else "no response"}
    raw = _strip_fences(rsp.get("content") or "")
    try:
        parsed = json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": f"JSON parse failed: {e}", "raw": raw[:500]}

    new_prompt = (parsed.get("new_prompt") or "").strip()
    if not new_prompt or len(new_prompt) < 32:
        return {"ok": False, "error": "critic returned empty/too-short prompt", "raw": raw[:500]}
    if len(new_prompt) > 5000:
        new_prompt = new_prompt[:5000]

    return {
        "ok": True,
        "agent_id": agent_id,
        "run_id": analysis.get("run_id"),
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
        "rationale": str(parsed.get("rationale") or "")[:2000],
        "diff_summary": list(parsed.get("diff_summary") or [])[:10],
        "failures_considered": len(failures),
    }


async def apply_revision(
    db: AsyncSession,
    *,
    agent_id: str,
    new_prompt: str,
    note: str = "",
) -> Dict[str, Any]:
    """Write `new_prompt` to the agent, keeping a rollback snapshot in capabilities."""
    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        return {"ok": False, "error": "agent not found"}
    new_prompt = (new_prompt or "").strip()
    if not new_prompt:
        return {"ok": False, "error": "new_prompt is empty"}

    caps = dict(agent.capabilities or {})
    history = list(caps.get("prompt_history") or [])
    history.append({
        "ts": datetime.utcnow().isoformat() + "Z",
        "note": note[:200],
        "prompt": agent.system_prompt or "",
    })
    caps["prompt_history"] = history[-10:]
    agent.capabilities = caps
    agent.system_prompt = new_prompt
    await db.flush()
    return {
        "ok": True,
        "agent_id": agent_id,
        "applied": True,
        "history_size": len(history),
    }


async def rollback_revision(
    db: AsyncSession, *, agent_id: str, steps: int = 1
) -> Dict[str, Any]:
    """Undo the last `steps` prompt revisions (default 1)."""
    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        return {"ok": False, "error": "agent not found"}
    caps = dict(agent.capabilities or {})
    history = list(caps.get("prompt_history") or [])
    if not history:
        return {"ok": False, "error": "no prompt history to rollback"}
    n = max(1, min(steps, len(history)))
    target = history[-n]
    remaining = history[: len(history) - n]
    caps["prompt_history"] = remaining
    agent.capabilities = caps
    agent.system_prompt = target.get("prompt") or ""
    await db.flush()
    return {"ok": True, "agent_id": agent_id, "restored_from": target.get("ts")}
