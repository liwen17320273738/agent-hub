"""Eval Runner — execute a dataset against the agent runtime.

Usage:
    run_id = await schedule_run(db, dataset_id="...", label="baseline")
    # async runner picks it up via run_dataset(db, run_id)

The runner is dataset-driven: it loads cases, fans out (sequentially for v0.1
to keep model/quota use predictable), runs each through `AgentRuntime`, scores
the output, and persists per-case `EvalResult` + an aggregate `EvalRun`.

Key design points:
  - Re-uses the EXACT same code path as /agents/run-by-role (via
    `_make_runtime_for_case`), so eval scores reflect production behavior.
  - Per-case timeout (asyncio.wait_for) so a hung tool doesn't stall the suite.
  - Fail-soft: a crashed case becomes a 0-score result with `error` set; the
    rest of the run continues.
  - Aggregates use weighted mean of `case.weight` (default 1.0).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent import AgentDefinition
from ..models.eval import EvalCase, EvalDataset, EvalResult, EvalRun

from ..api.agents import _resolve_runtime_agent_id

logger = logging.getLogger(__name__)


async def _build_runtime(
    db: AsyncSession,
    *,
    seed_id: str,
    model_override: str = "",
    max_steps: int = 5,
    temperature: float = 0.5,
):
    from ..agents.seed import AGENT_TOOLS
    from .agent_delegate import _SHORT_PROMPTS
    from .agent_runtime import AgentRuntime

    agent_def = await db.get(AgentDefinition, seed_id)
    bound_tools = list(AGENT_TOOLS.get(seed_id, []))
    system_prompt = (
        (agent_def.system_prompt if agent_def and agent_def.system_prompt else "")
        or _SHORT_PROMPTS.get(seed_id, "你是一位资深领域专家。")
    )
    model_pref: Dict[str, str] = {}
    if model_override:
        model_pref["execution"] = model_override
    elif agent_def and agent_def.preferred_model:
        model_pref["execution"] = agent_def.preferred_model

    return AgentRuntime(
        agent_id=seed_id,
        system_prompt=system_prompt,
        tools=bound_tools,
        model_preference=model_pref or None,
        max_steps=max_steps,
        temperature=temperature,
    )


async def schedule_run(
    db: AsyncSession,
    *,
    dataset_id: str,
    label: str = "",
    agent_role_override: str = "",
    model_override: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a pending EvalRun row and return its id. The caller should
    then schedule `run_dataset(db, run_id)` as a background task.
    """
    dataset = await db.get(EvalDataset, dataset_id)
    if not dataset:
        raise ValueError(f"dataset not found: {dataset_id}")
    cases = (await db.execute(
        select(EvalCase).where(EvalCase.dataset_id == dataset_id, EvalCase.enabled.is_(True))
    )).scalars().all()
    run = EvalRun(
        dataset_id=dataset_id,
        label=label or f"{dataset.name} @ {datetime.utcnow().isoformat(timespec='seconds')}",
        agent_role_override=agent_role_override,
        model_override=model_override,
        status="pending",
        total_cases=len(cases),
        metadata_extra=metadata or {},
    )
    db.add(run)
    await db.flush()
    run_id = str(run.id)
    await db.commit()
    return run_id


async def run_dataset(db: AsyncSession, run_id: str) -> Dict[str, Any]:
    """Execute a previously-scheduled run end-to-end."""
    from .eval_scorer import run_scorer

    run = await db.get(EvalRun, run_id)
    if not run:
        return {"ok": False, "error": "run not found"}
    if run.status not in ("pending", "running"):
        return {"ok": False, "error": f"run already {run.status}"}
    dataset = await db.get(EvalDataset, run.dataset_id) if run.dataset_id else None

    cases = (await db.execute(
        select(EvalCase).where(EvalCase.dataset_id == run.dataset_id, EvalCase.enabled.is_(True))
    )).scalars().all() if run.dataset_id else []

    run.status = "running"
    run.total_cases = len(cases)
    await db.flush()
    await db.commit()

    total_weight = 0.0
    total_score = 0.0
    total_latency = 0
    total_tokens = 0
    passed = failed = skipped = 0

    for case in cases:
        role = (run.agent_role_override or case.role or
                (dataset.target_role if dataset else "")).strip()
        seed_id = await _resolve_runtime_agent_id(db, role) if role else None
        if not seed_id:
            skipped += 1
            db.add(EvalResult(
                run_id=run.id, case_id=case.id, case_name=case.name,
                role=role, seed_id="", score=0.0, passed=False,
                scorer=case.scorer, error=f"unresolvable role: {role!r}",
            ))
            continue

        try:
            runtime = await _build_runtime(
                db, seed_id=seed_id,
                model_override=run.model_override,
                max_steps=5, temperature=0.3,
            )
        except Exception as e:
            failed += 1
            db.add(EvalResult(
                run_id=run.id, case_id=case.id, case_name=case.name,
                role=role, seed_id=seed_id, score=0.0, passed=False,
                scorer=case.scorer, error=f"runtime build failed: {e}",
            ))
            continue

        started = time.monotonic()
        timeout = max(10, int(case.timeout_seconds or 120))
        try:
            exec_result = await asyncio.wait_for(
                runtime.execute(db, task=case.task, context=case.context or None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            failed += 1
            db.add(EvalResult(
                run_id=run.id, case_id=case.id, case_name=case.name,
                role=role, seed_id=seed_id,
                score=0.0, passed=False,
                scorer=case.scorer, error=f"timeout after {timeout}s",
                latency_ms=int((time.monotonic() - started) * 1000),
            ))
            continue
        except Exception as e:
            failed += 1
            db.add(EvalResult(
                run_id=run.id, case_id=case.id, case_name=case.name,
                role=role, seed_id=seed_id,
                score=0.0, passed=False,
                scorer=case.scorer, error=f"runtime crashed: {e}",
                latency_ms=int((time.monotonic() - started) * 1000),
            ))
            continue

        latency_ms = int((time.monotonic() - started) * 1000)
        output = (exec_result or {}).get("content", "") or ""
        observations = list((exec_result or {}).get("observations") or [])[:50]
        steps = int((exec_result or {}).get("steps", 0) or 0)
        runtime_error = (exec_result or {}).get("error")

        scored = await run_scorer(case.scorer, output, case.expected or {}, task=case.task)
        score = float(scored.get("score") or 0.0)
        passed_case = bool(scored.get("passed"))
        if passed_case:
            passed += 1
        else:
            failed += 1

        weight = float(case.weight or 1.0)
        total_weight += weight
        total_score += score * weight
        total_latency += latency_ms

        db.add(EvalResult(
            run_id=run.id, case_id=case.id, case_name=case.name,
            role=role, seed_id=seed_id,
            score=score, passed=passed_case,
            output=output[:8000],
            observations=observations,
            scorer=case.scorer, scorer_detail=scored.get("detail") or {},
            error=runtime_error or "",
            steps=steps, latency_ms=latency_ms,
        ))
        await db.flush()

    run.passed_cases = passed
    run.failed_cases = failed
    run.skipped_cases = skipped
    run.avg_score = (total_score / total_weight) if total_weight else 0.0
    run.avg_latency_ms = (total_latency / max(1, passed + failed)) if (passed + failed) else 0.0
    run.total_tokens = total_tokens
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    await db.flush()
    await db.commit()

    return {
        "ok": True,
        "run_id": str(run.id),
        "passed": passed, "failed": failed, "skipped": skipped,
        "avg_score": run.avg_score, "avg_latency_ms": run.avg_latency_ms,
    }
