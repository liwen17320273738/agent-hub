"""
Execute Full Pipeline — the public entry point for running a complete
8-stage pipeline. Extracted from pipeline_engine.py to reduce god-file size.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from .pipeline_engine import execute_stage
from .stage_constants import (
    STAGE_ROLE_PROMPTS,
    AGENT_PROFILES,
    _AGENT_KEY_TO_SEED_ID,
    STAGE_REVIEW_CONFIG,
    MAX_REVIEW_RETRIES,
)
from .stage_layers import (
    review_stage_output,
    _parse_reject_to,
    _extract_reject_reason,
)
from .observability import start_trace, complete_trace
from .memory import update_quality_score
from .sse import emit_event

logger = logging.getLogger(__name__)

# Human-readable labels for stages, used when auto-creating a stage row that
# the task template never created (otherwise the dashboard can never show it).
_STAGE_LABELS = {
    "planning": "需求规划",
    "design": "UI/UX 设计",
    "architecture": "架构设计",
    "development": "开发实现",
    "testing": "测试验证",
    "reviewing": "审查验收",
    "acceptance": "验收确认",
    "deployment": "部署上线",
    "preview": "预览发布",
}


async def _stage_heartbeat(task_id: str, stage_id: str, interval: int = 30) -> None:
    """Emit a periodic liveness event while a stage runs.

    Lets the dashboard distinguish "still working" from "silently hung at 0%
    CPU". Cancelled by the caller as soon as the stage finishes or times out.
    """
    elapsed = 0
    try:
        while True:
            await asyncio.sleep(interval)
            elapsed += interval
            await emit_event("stage:heartbeat", {
                "taskId": task_id,
                "stageId": stage_id,
                "elapsedSeconds": elapsed,
            })
    except asyncio.CancelledError:
        return
    except Exception:
        # A heartbeat must never take down the stage it's monitoring.
        return


async def execute_full_pipeline(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    stages: Optional[List[str]] = None,
    available_providers: Optional[List[str]] = None,
    complexity: Optional[str] = None,
    force_continue: bool = False,
    prior_outputs: Optional[Dict[str, str]] = None,
    project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a full pipeline with all maturation layers.
    Persists each stage result to DB and emits SSE events in real-time.
    When force_continue=True, verification warnings/failures are logged
    but the pipeline continues (used by auto-run).
    prior_outputs: outputs from already-completed stages (used when resuming).
    """
    from ..models.pipeline import PipelineTask, PipelineStage

    if stages is None:
        stages = list(STAGE_ROLE_PROMPTS.keys())

    trace = await start_trace(task_id, task_title)
    outputs: Dict[str, str] = dict(prior_outputs) if prior_outputs else {}
    results: List[Dict[str, Any]] = []
    # Track stages that hard-failed while force_continue kept the pipeline
    # going. Used so the final result honestly reports degradation instead of
    # masquerading as a clean success.
    failed_stages: List[Dict[str, str]] = []

    await emit_event("pipeline:auto-start", {
        "taskId": task_id,
        "title": task_title,
        "stages": stages,
        "agentTeam": [
            {"stage": sid, **AGENT_PROFILES.get(STAGE_ROLE_PROMPTS[sid].get("agent", ""), {})}
            for sid in stages if sid in STAGE_ROLE_PROMPTS
        ],
    })

    # Load the task and its stages from DB
    import uuid as _uuid
    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        task_uuid = None

    db_task: Optional[PipelineTask] = None
    db_stages: Dict[str, PipelineStage] = {}
    if task_uuid:
        result = await db.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == task_uuid)
        )
        db_task = result.scalar_one_or_none()
        if db_task:
            db_stages = {s.stage_id: s for s in db_task.stages}

    # Ensure task worktree exists for post-stage hooks
    task_worktree = None
    try:
        from .task_workspace import ensure_task_workspace
        task_worktree = await ensure_task_workspace(task_id, task_title)
    except Exception as ws_err:
        logger.warning("[pipeline] Failed to ensure task workspace: %s", ws_err)

    for stage_id in stages:
        logger.info(f"[pipeline] Executing stage: {stage_id}")
        # ── 双重同行评审设计说明 ──
        # 每个阶段有两处同行评审，这不是重复，而是分工：
        # 1. 早期评审（质量门禁之前，行 3089-3130）：快速把关，在进入昂贵的质量门禁
        #    LLM 调用之前先过滤掉明显不合格的产出。通过则缓存结果跳过第二轮。
        # 2. 后期评审（质量门禁之后，行 3297-3433）：带重试循环 + 反馈注入的深度评审。
        #    如果早期已通过则自动跳过（避免重复调用），仅在早期拒绝或未配置时进入。
        # 这种「早期快速拒绝 + 后期深度修复」的设计可以节省约 50% 的审阅延迟/成本。
        early_peer_review_ok: Optional[Dict[str, Any]] = None

        # Ensure a DB row exists for this stage. The task template only creates
        # rows for its own stage list; when auto-run executes a stage that the
        # template never declared (e.g. the full 8-stage flow on a minimal
        # template), every `if stage_id in db_stages` write below is silently
        # skipped and the stage stays invisible on the dashboard. Create the
        # missing row so execution is always observable.
        if db_task and stage_id not in db_stages:
            try:
                role_info = STAGE_ROLE_PROMPTS.get(stage_id, {})
                new_stage = PipelineStage(
                    task_id=db_task.id,
                    stage_id=stage_id,
                    label=_STAGE_LABELS.get(stage_id, stage_id),
                    status="pending",
                    owner_role=role_info.get("role", ""),
                    sort_order=stages.index(stage_id),
                )
                db.add(new_stage)
                await db.flush()
                db_stages[stage_id] = new_stage
                logger.info("[pipeline] Auto-created missing stage row: %s", stage_id)
            except Exception as create_err:
                logger.warning(
                    "[pipeline] Failed to auto-create stage row %s: %s",
                    stage_id, create_err,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass

        # Mark current stage as active in DB
        if db_task:
            db_task.current_stage_id = stage_id
            if stage_id in db_stages:
                db_stages[stage_id].status = "active"
                db_stages[stage_id].started_at = datetime.utcnow()
            try:
                # Commit (not just flush) so the dashboard sees the stage go
                # active immediately. The whole pipeline used to run in one
                # transaction committed only at the very end, so a mid-run hang
                # left every stage stuck at "pending" forever.
                await db.commit()
            except Exception as flush_err:
                logger.warning("[pipeline] DB commit failed marking stage active: %s", flush_err)
                try:
                    await db.rollback()
                except Exception:
                    logger.debug("[pipeline] DB rollback after commit failure failed for stage %s", stage_id, exc_info=True)

        # Per-stage watchdog: execute_stage already bounds its own LLM call,
        # but the post-LLM Phase 4/6/7 blocks (codegen subprocess, Playwright
        # browser smoke, local preview server) can each await on a child
        # process or socket that lacks its own timeout. A total wall-clock
        # ceiling here guarantees a stage can never hang the whole pipeline at
        # 0% CPU forever — it aborts, records an honest error, and (under
        # force_continue) moves on. A heartbeat keeps the dashboard informed
        # that the stage is still alive rather than silently stuck.
        _stage_budget = max(int(settings.phase_timeout_seconds or 1800), 120)
        _hb = asyncio.create_task(_stage_heartbeat(task_id, stage_id))
        try:
            result = await asyncio.wait_for(
                execute_stage(
                    db,
                    task_id=task_id,
                    task_title=task_title,
                    task_description=task_description,
                    stage_id=stage_id,
                    previous_outputs=outputs,
                    trace=trace,
                    available_providers=available_providers,
                    complexity=complexity,
                    project_path=project_path,
                ),
                timeout=_stage_budget,
            )
        except asyncio.TimeoutError:
            logger.error(
                "[pipeline] Stage %s exceeded phase wall-clock %ds — aborting stage",
                stage_id, _stage_budget,
            )
            # The cancelled coroutine may have left the shared session mid-op;
            # reset it so subsequent stages can still commit.
            try:
                await db.rollback()
            except Exception:
                logger.debug("[pipeline] rollback after stage timeout failed", exc_info=True)
            result = {
                "ok": False,
                "error": (
                    f"阶段执行超过总时限 {_stage_budget}s"
                    "（疑似无超时的网络/子进程等待挂起），已中止该阶段"
                ),
                "timeout": True,
            }
        finally:
            _hb.cancel()
            try:
                await _hb
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("[pipeline] heartbeat cleanup error", exc_info=True)

        results.append({"stage_id": stage_id, **result})

        if not result.get("ok"):
            # Persist error state to DB
            if stage_id in db_stages:
                db_stages[stage_id].status = "blocked" if result.get("blocked") else "error"
            if db_task:
                db_task.status = "paused" if result.get("blocked") else "active"
            # Phase 4.2b: write scheduler_last_error for build failure or stage error
            if result.get("build_log_summary"):
                err_msg = result["error"][:500]
            else:
                err_msg = result.get("error", "Stage execution failed")[:500]
            if db_task:
                db_task.scheduler_last_error = err_msg
            try:
                await db.commit()
            except Exception as flush_err:
                logger.warning("[pipeline] DB commit failed persisting error state: %s", flush_err)
                try:
                    await db.rollback()
                except Exception:
                    pass

            if result.get("blocked") and not force_continue:
                await complete_trace(trace.trace_id, status="blocked")
                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": result.get("reason", "Blocked by guardrail"),
                })
                return {
                    "ok": False,
                    "blocked": True,
                    "stopped_at": stage_id,
                    "approval_id": result.get("approval_id"),
                    "reason": result.get("reason", "Blocked by guardrail"),
                    "results": results,
                    "trace_id": trace.trace_id,
                }

            if force_continue:
                logger.warning(
                    f"[pipeline] Stage {stage_id} failed but force_continue=True, skipping to next"
                )
                failed_stages.append({
                    "stage_id": stage_id,
                    "error": (result.get("error") or "Unknown error")[:500],
                })
                await emit_event("stage:error", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "error": result.get("error", "Unknown error"),
                    "continuing": True,
                })
                continue

            # Honest terminal state: a non-forced failed stage stops the run,
            # so reflect that on the task instead of leaving it "active".
            if db_task:
                db_task.status = "failed"
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            await complete_trace(trace.trace_id, status="failed")
            await emit_event("pipeline:auto-error", {
                "taskId": task_id,
                "stoppedAt": stage_id,
                "error": result.get("error", "Unknown error"),
            })
            return {
                "ok": False,
                "stopped_at": stage_id,
                "error": result.get("error"),
                "results": results,
                "trace_id": trace.trace_id,
            }

        content = result.get("content", "")
        outputs[stage_id] = content

        # Persist stage output + verification data
        verification = result.get("verification", {})
        quality_score = 0.8 if verification.get("status") == "pass" else 0.5 if verification.get("status") == "warn" else 0.2
        if stage_id in db_stages:
            db_stages[stage_id].output = content
            db_stages[stage_id].verify_status = verification.get("status")
            db_stages[stage_id].verify_checks = verification.get("checks")
            db_stages[stage_id].quality_score = quality_score
        try:
            await db.commit()
        except Exception as flush_err:
            logger.warning("[pipeline] DB commit failed persisting stage output: %s", flush_err)
            try:
                await db.rollback()
            except Exception:
                pass

        # Write to delivery docs on disk (dual-write: global legacy + task-scoped)
        try:
            from ..api.delivery_docs import write_stage_output
            await write_stage_output(stage_id, content)
        except Exception as doc_err:
            logger.warning(f"[pipeline] Failed to write legacy delivery doc for {stage_id}: {doc_err}")
        try:
            from .task_workspace import write_stage_output_v2
            await write_stage_output_v2(task_id, task_title, stage_id, content)
        except Exception as ws_err:
            logger.warning(f"[pipeline] Failed to write task workspace doc for {stage_id}: {ws_err}")

        # Note: artifact writing is now handled inside execute_stage() (Layer 10)
        # to ensure artifacts are written even when stages are run individually.
        # The duplicate call here has been removed to avoid double-writing.

        # --- Peer Review (Layer 11) ---
        review_config = STAGE_REVIEW_CONFIG.get(stage_id)
        if review_config and review_config.get("reviewer_agent"):
            try:
                review_result = await review_stage_output(
                    db,
                    task_id=task_id,
                    stage_id=stage_id,
                    stage_output=content,
                    task_title=task_title,
                    task_description=task_description,
                    previous_outputs=outputs,
                )
                if stage_id in db_stages:
                    db_stages[stage_id].review_status = "approved" if review_result.get("approved") else "rejected"
                    db_stages[stage_id].reviewer_feedback = review_result.get("feedback", "")
                    db_stages[stage_id].reviewer_agent = review_result.get("reviewer_agent", "")
                    db_stages[stage_id].review_attempts = (db_stages[stage_id].review_attempts or 0) + 1
                await db.flush()

                if review_result.get("approved"):
                    early_peer_review_ok = review_result
                else:
                    # Do NOT hard-pause on the first reject. Leaving
                    # early_peer_review_ok as None lets the post-gate review
                    # path run the rework loop — the authoring agent revises
                    # with the reviewer's feedback (up to MAX_REVIEW_RETRIES)
                    # and is only paused if it still can't satisfy the
                    # reviewer. Instant-pausing here skipped rework entirely,
                    # which dead-ended every run on the first critical note.
                    early_peer_review_ok = None
                    await emit_event("stage:peer-review-rework-pending", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "reviewer": review_result.get("reviewer", ""),
                        "feedback": review_result.get("feedback", "")[:500],
                    })
            except Exception as review_err:
                logger.warning("[pipeline] Peer review failed for %s: %s", stage_id, review_err)

        # --- Post-stage hooks (code extraction, test validation, etc.) ---
        try:
            from .stage_hooks import run_hooks, HookContext
            post_ctx = HookContext(
                task_id=task_id, stage_id=stage_id, worktree=task_worktree,
                content=content, model=result.get("model", ""),
                agent_id=_AGENT_KEY_TO_SEED_ID.get(
                    STAGE_ROLE_PROMPTS.get(stage_id, {}).get("agent", ""), ""),
            )
            post_results = await run_hooks("post", post_ctx)
            if post_results:
                logger.info("[pipeline] Post-hooks for %s: %s", stage_id, post_results)
                for pr in post_results:
                    if not pr.get("ok") and stage_id in db_stages:
                        err = pr.get("error", "hook failed")
                        db_stages[stage_id].last_error = (err or "")[:2000]
                await emit_event("stage:hooks-complete", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "hooks": post_results,
                })
        except Exception as hook_err:
            logger.warning("[pipeline] Post-stage hooks failed for %s: %s", stage_id, hook_err)
            if stage_id in db_stages:
                db_stages[stage_id].last_error = str(hook_err)[:2000]

        # --- Layer 3.7: Skill Completion Criteria Validation ---
        skill_criteria_results = []
        skill_completion_criteria = result.get("skill_completion_criteria") or []
        if skill_completion_criteria and content:
            try:
                from .role_card_builder import build_skill_criteria_check
                skill_criteria_results = build_skill_criteria_check(content, skill_completion_criteria)
                passed = sum(1 for r in skill_criteria_results if r["passed"])
                total = len(skill_criteria_results)
                logger.info(
                    "[pipeline] Skill criteria for %s: %d/%d passed",
                    stage_id, passed, total,
                )
                await emit_event("stage:skill-criteria", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "passed": passed,
                    "total": total,
                    "results": skill_criteria_results,
                })
            except Exception as sc_err:
                logger.warning("[pipeline] Skill criteria check failed: %s", sc_err)

        # --- Quality Gate Evaluation ---
        gate_result = None
        try:
            from .quality_gates import evaluate_quality_gate
            from .self_verify import StageVerification, VerifyStatus, VerifyResult

            heuristic = StageVerification(
                stage_id=stage_id, role="",
                overall_status=VerifyStatus(verification.get("status", "pass")),
                checks=[VerifyResult(check_name=c.get("check_name", c.get("name", "")), status=VerifyStatus(c.get("status", "pass")), message=c.get("message", "")) for c in verification.get("checks", [])],
                auto_proceed=verification.get("auto_proceed", True),
            )
            task_template = db_task.template if db_task else None
            # Per-task overrides set via the dashboard's "门禁阈值" drawer
            # take precedence over template/global defaults — see
            # quality_gates._get_stage_config for the merge rules.
            task_overrides = (db_task.quality_gate_config if db_task else None) or None
            gate_result = await evaluate_quality_gate(
                stage_id, content,
                template=task_template,
                previous_outputs=outputs,
                heuristic_result=heuristic,
                skip_llm=force_continue,
                task_overrides=task_overrides,
            )

            if stage_id in db_stages:
                db_stages[stage_id].gate_status = gate_result.overall_status.value
                db_stages[stage_id].gate_score = gate_result.overall_score
                db_stages[stage_id].gate_details = {
                    "checks": [c.model_dump() for c in gate_result.checks],
                    "suggestions": gate_result.suggestions,
                    "block_reason": gate_result.block_reason,
                }
            await db.flush()

            await emit_event("stage:quality-gate", {
                "taskId": task_id,
                "stageId": stage_id,
                "gateStatus": gate_result.overall_status.value,
                "gateScore": gate_result.overall_score,
                "canProceed": gate_result.can_proceed,
                "blockReason": gate_result.block_reason,
            })

            if not gate_result.can_proceed and not force_continue:
                if db_task:
                    db_task.status = "paused"
                if stage_id in db_stages:
                    db_stages[stage_id].status = "blocked"
                await db.flush()
                await complete_trace(trace.trace_id, status="paused")

                # Learning loop — persist GATE_FAIL signal
                try:
                    from .learning_loop import capture_signal
                    await capture_signal(
                        db, task_id=task_id, stage_id=stage_id,
                        role=STAGE_ROLE_PROMPTS.get(stage_id, {}).get("role", ""),
                        signal_type="GATE_FAIL", severity="error",
                        reviewer_feedback=gate_result.block_reason,
                        output_excerpt=content,
                        quality_score=gate_result.overall_score,
                        metadata={"suggestions": gate_result.suggestions},
                    )
                except Exception as exc:
                    logger.debug("[learning] GATE_FAIL signal capture failed: %s", exc)

                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": f"质量门禁未通过: {gate_result.block_reason or '评分过低'}",
                    "gateScore": gate_result.overall_score,
                })
                return {
                    "ok": False,
                    "paused": True,
                    "stopped_at": stage_id,
                    "reason": f"Quality gate failed: {gate_result.block_reason}",
                    "gate_result": gate_result.model_dump(),
                    "results": results,
                    "trace_id": trace.trace_id,
                }
        except Exception as gate_err:
            logger.warning(f"[pipeline] Quality gate evaluation failed for {stage_id}: {gate_err}")

        if not verification.get("auto_proceed", True):
            if force_continue:
                logger.warning(
                    f"[pipeline] Stage {stage_id} verification failed but force_continue=True, proceeding"
                )
                await emit_event("stage:verify-warn", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "checks": verification.get("checks", []),
                    "suggestions": verification.get("suggestions", []),
                })
            else:
                if db_task:
                    db_task.status = "paused"
                await db.flush()
                await complete_trace(trace.trace_id, status="paused")
                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": "Verification requires human review",
                })
                return {
                    "ok": False,
                    "paused": True,
                    "stopped_at": stage_id,
                    "reason": "Verification failed, requires human review",
                    "results": results,
                    "trace_id": trace.trace_id,
                }

        # --- Peer Review: downstream agent reviews this stage's output ---
        review_conf = STAGE_REVIEW_CONFIG.get(stage_id, {})
        from .learning_loop import get_active_addendum as _get_active_addendum
        _task_tpl = db_task.template if db_task else None
        active_addendum = await _get_active_addendum(
            db, stage_id=stage_id, template=_task_tpl, complexity=complexity,
        )
        if review_conf.get("reviewer_agent") and not force_continue:
            # 后期评审入口：如果早期评审已通过，直接复用结果跳过此轮（避免重复 LLM 调用）
            if early_peer_review_ok is not None and early_peer_review_ok.get("approved"):
                results[-1]["review"] = early_peer_review_ok
                logger.info(
                    "[pipeline] Stage %s peer review: skipping duplicate post-gate reviewer call",
                    stage_id,
                )
            retries = 0
            while (
                early_peer_review_ok is None or not early_peer_review_ok.get("approved")
            ) and retries < MAX_REVIEW_RETRIES:
                if stage_id in db_stages:
                    db_stages[stage_id].status = "reviewing"
                await db.flush()

                review_result = await review_stage_output(
                    db,
                    task_id=task_id,
                    stage_id=stage_id,
                    stage_output=content,
                    task_title=task_title,
                    task_description=task_description,
                    previous_outputs=outputs,
                    injected_override_id=(
                        active_addendum.get("id") if active_addendum else None
                    ),
                    injected_override_mode=(
                        active_addendum.get("mode") if active_addendum else None
                    ),
                )

                results[-1]["review"] = review_result

                if stage_id in db_stages:
                    db_stages[stage_id].reviewer_agent = review_result.get("reviewer", "")
                    db_stages[stage_id].reviewer_feedback = review_result.get("feedback", "")
                    db_stages[stage_id].review_attempts = retries + 1

                if review_result.get("approved", True):
                    logger.info(f"[pipeline] Stage {stage_id} peer review: APPROVED by {review_result.get('reviewer', '?')}")
                    if stage_id in db_stages:
                        db_stages[stage_id].review_status = "approved"
                    await db.flush()
                    break

                retries += 1
                feedback = review_result.get("feedback", "")
                logger.warning(f"[pipeline] Stage {stage_id} peer review: REJECTED (attempt {retries}/{MAX_REVIEW_RETRIES})")

                if stage_id in db_stages:
                    db_stages[stage_id].review_status = "rejected"
                await db.flush()

                if retries >= MAX_REVIEW_RETRIES:
                    # Peer review is a SECONDARY (advisory) opinion. The
                    # authoritative quality bar is the deterministic quality
                    # gate, which already ran above. If the gate PASSED, a
                    # lingering peer-review reject should NOT dead-end the
                    # pipeline — it becomes a recorded warning and we proceed.
                    # We only hard-pause when the gate itself did not pass
                    # (i.e. the objective checks agree the output is bad).
                    gate_ok = gate_result is not None and gate_result.can_proceed
                    if gate_ok:
                        logger.warning(
                            "[pipeline] Stage %s peer review still rejected after "
                            "%d retries, but quality gate passed (score=%.2f) — "
                            "proceeding with advisory warning.",
                            stage_id, MAX_REVIEW_RETRIES,
                            gate_result.overall_score,
                        )
                        if stage_id in db_stages:
                            db_stages[stage_id].review_status = "advisory_rejected"
                        await db.flush()
                        await emit_event("stage:peer-review-advisory", {
                            "taskId": task_id,
                            "stageId": stage_id,
                            "reason": "Peer review rejected but quality gate passed — proceeding",
                            "feedback": feedback[:500],
                            "gateScore": gate_result.overall_score,
                        })
                        break
                    if db_task:
                        db_task.status = "paused"
                    if stage_id in db_stages:
                        db_stages[stage_id].status = "rejected"
                    await db.flush()
                    await emit_event("pipeline:auto-paused", {
                        "taskId": task_id,
                        "stoppedAt": stage_id,
                        "reason": f"Peer review rejected after {MAX_REVIEW_RETRIES} retries",
                        "feedback": feedback[:500],
                    })
                    return {
                        "ok": False,
                        "paused": True,
                        "stopped_at": stage_id,
                        "reason": f"Peer review rejected by {review_result.get('reviewer', '?')}",
                        "review_feedback": feedback,
                        "results": results,
                        "trace_id": trace.trace_id,
                    }

                # Re-execute stage with reviewer feedback injected.
                # We pass the *rejected* draft along with the event so the
                # frontend's "self-heal" drawer can show a before/after diff
                # without needing a separate API round-trip. The DB column
                # ``output`` will be overwritten on the next iteration, so
                # this is the only place we get to capture the rejected
                # version.
                rejected_draft = (
                    db_stages[stage_id].output
                    if stage_id in db_stages
                    else (results[-1].get("content", "") if results else "")
                )
                await emit_event("stage:rework", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "attempt": retries + 1,
                    "feedback": feedback[:300],
                    "rejectedDraft": (rejected_draft or "")[:4000],
                    "rejectedDraftTruncated": bool(rejected_draft and len(rejected_draft) > 4000),
                    "reviewer": review_result.get("reviewer", ""),
                })

                rework_outputs = dict(outputs)
                rework_outputs[f"{stage_id}_review_feedback"] = (
                    f"## 审阅反馈（来自 {review_result.get('reviewer', '审阅者')}）\n\n"
                    f"{feedback}\n\n请根据以上反馈修改你的产出。"
                )

                if stage_id in db_stages:
                    db_stages[stage_id].status = "active"
                    db_stages[stage_id].started_at = datetime.utcnow()
                await db.flush()

                rework = await execute_stage(
                    db,
                    task_id=task_id,
                    task_title=task_title,
                    task_description=task_description,
                    stage_id=stage_id,
                    previous_outputs=rework_outputs,
                    trace=trace,
                    available_providers=available_providers,
                    complexity=complexity,
                )

                if not rework.get("ok"):
                    break

                content = rework.get("content", "")
                outputs[stage_id] = content
                results[-1] = {"stage_id": stage_id, **rework}

                if stage_id in db_stages:
                    db_stages[stage_id].output = content
                await db.flush()

        # --- Human Approval Gate ---
        if review_conf.get("human_gate") and not force_continue:
            from .guardrails import ApprovalRequest, GuardrailLevel as GL, _store_approval
            approval = ApprovalRequest(
                task_id=task_id,
                stage_id=stage_id,
                action=f"approve_{stage_id}",
                description=f"阶段「{stage_id}」已完成，需要人工审批确认后才能继续",
                risk_level=GL.REQUIRE_REVIEW,
                requested_by="pipeline",
            )
            await _store_approval(approval)

            if db_task:
                db_task.status = "paused"
            if stage_id in db_stages:
                db_stages[stage_id].status = "awaiting_approval"
                db_stages[stage_id].approval_id = approval.id
            await db.flush()

            await emit_event("stage:awaiting-approval", {
                "taskId": task_id,
                "stageId": stage_id,
                "approvalId": approval.id,
                "label": f"阶段「{stage_id}」等待人工审批...",
            })

            # 跨渠道通知：IM / webhook / 邮件
            if db_task:
                try:
                    from .notify import broadcast_task_event
                    stage_label = {
                        "planning": "需求规划", "design": "UI/UX 设计",
                        "architecture": "架构设计", "development": "开发实现",
                        "testing": "测试验证", "reviewing": "审查验收",
                        "deployment": "部署上线",
                    }.get(stage_id, stage_id)
                    await broadcast_task_event(
                        db_task,
                        event="awaiting_approval",
                        message=f"阶段「{stage_label}」已完成，等待人工审批",
                        extras={
                            "阶段": stage_label,
                            "审批ID": approval.id,
                            "操作": f"前往 {task_id[:8]} 详情页进行审批",
                        },
                    )
                except Exception as notify_err:
                    logger.debug("[pipeline] approval notification failed: %s", notify_err)

            await complete_trace(trace.trace_id, status="paused")
            return {
                "ok": False,
                "paused": True,
                "awaiting_approval": True,
                "approval_id": approval.id,
                "stopped_at": stage_id,
                "reason": f"阶段 {stage_id} 需要人工审批",
                "results": results,
                "trace_id": trace.trace_id,
            }

        # --- Hermes Oversight: unified supervision before stage finalization ---
        try:
            from .hermes_oversight import run_hermes_oversight
            content_to_check = content or ""
            hermes_report = await run_hermes_oversight(
                db,
                task_id=task_id,
                stage_id=stage_id,
                role=STAGE_ROLE_PROMPTS.get(stage_id, {}).get("role", ""),
                content=content_to_check,
                previous_outputs=outputs,
                force_continue=force_continue,
            )
            if hermes_report.overall_score < 7.0:
                logger.info(
                    "[hermes] Stage %s score=%.1f — %s",
                    stage_id, hermes_report.overall_score, hermes_report.verdict.value,
                )

            await emit_event("stage:hermes-oversight", {
                "taskId": task_id,
                "stageId": stage_id,
                "verdict": hermes_report.verdict.value,
                "overallScore": hermes_report.overall_score,
                "summary": hermes_report.summary,
            })

            if stage_id in db_stages:
                db_stages[stage_id].hermes_score = hermes_report.overall_score
                db_stages[stage_id].hermes_verdict = hermes_report.verdict.value
        except Exception as hermes_err:
            logger.warning("[hermes] Oversight failed for %s: %s", stage_id, hermes_err)

        # Mark stage as finalized
        if stage_id in db_stages:
            db_stages[stage_id].status = "done"
            db_stages[stage_id].completed_at = datetime.utcnow()
        await db.flush()

        # --- Acceptance REJECT_TO detection (reviewing stage only) ---
        # The acceptance agent can output "REJECTED REJECT_TO: <target_stage>"
        # to indicate the deliverable should be reworked from a specific stage.
        # When detected, we auto-rework from that stage instead of proceeding.
        if stage_id == "reviewing" and content:
            reject_to_stage = _parse_reject_to(content)
            if reject_to_stage and reject_to_stage in stages:
                reject_idx = stages.index(reject_to_stage)
                current_idx = stages.index(stage_id)
                if reject_idx < current_idx:
                    reject_reason = _extract_reject_reason(content)
                    logger.info(
                        "[pipeline] Acceptance REJECT_TO: %s → reworking from %s",
                        task_id, reject_to_stage,
                    )
                    await emit_event("pipeline:acceptance-reject-to", {
                        "taskId": task_id,
                        "rejectToStage": reject_to_stage,
                        "reason": reject_reason[:500],
                    })

                    for s_id in stages[reject_idx:current_idx + 1]:
                        if s_id in db_stages:
                            db_stages[s_id].status = "pending"
                            if s_id == reject_to_stage:
                                db_stages[s_id].reject_feedback = reject_reason[:2000]
                    if db_task:
                        db_task.current_stage_id = reject_to_stage
                    await db.flush()

                    rework_stages = stages[reject_idx:]
                    for rework_sid in rework_stages:
                        rework_reject_fb = None
                        if rework_sid == reject_to_stage:
                            rework_reject_fb = reject_reason

                        if rework_sid in db_stages:
                            db_stages[rework_sid].status = "active"
                            db_stages[rework_sid].started_at = datetime.utcnow()
                        await db.flush()

                        rework_result = await execute_stage(
                            db,
                            task_id=task_id,
                            task_title=task_title,
                            task_description=task_description,
                            stage_id=rework_sid,
                            previous_outputs=outputs,
                            trace=trace,
                            available_providers=available_providers,
                            complexity=complexity,
                            reject_feedback=rework_reject_fb,
                            reject_count=1,
                        )
                        if rework_result.get("ok"):
                            rework_content = rework_result.get("content", "")
                            outputs[rework_sid] = rework_content
                            results.append({"stage_id": rework_sid, **rework_result})
                            if rework_sid in db_stages:
                                db_stages[rework_sid].output = rework_content
                                db_stages[rework_sid].status = "done"
                                db_stages[rework_sid].completed_at = datetime.utcnow()
                            await db.flush()
                        else:
                            if db_task:
                                db_task.status = "paused"
                            await db.flush()
                            return {
                                "ok": False,
                                "paused": True,
                                "stopped_at": rework_sid,
                                "reason": f"Rework failed at {rework_sid} after acceptance REJECT_TO",
                                "results": results,
                                "trace_id": trace.trace_id,
                            }

        if stage_id != stages[0]:
            prev_stage = stages[stages.index(stage_id) - 1]
            await update_quality_score(db, task_id, prev_stage, 0.8)

    # All stages complete — compute overall quality. Status decision below.
    if db_task:
        q_scores = [
            float(s.quality_score)
            for s in db_task.stages
            if s.quality_score is not None and float(s.quality_score) > 0
        ]
        if q_scores:
            db_task.overall_quality_score = round(sum(q_scores) / len(q_scores), 3)
        else:
            gate_scores = [
                float(s.gate_score) for s in db_task.stages
                if s.gate_score is not None
            ]
            if gate_scores:
                db_task.overall_quality_score = round(
                    sum(gate_scores) / len(gate_scores), 3
                )
    await db.flush()

    # Auto-compile deliverables
    try:
        from ..api.delivery_docs import compile_deliverables
        deliverable_md = await compile_deliverables(task_id, db)
        logger.info(f"[pipeline] Compiled deliverables for task {task_id} ({len(deliverable_md)} chars)")
    except Exception as e:
        logger.warning(f"[pipeline] Failed to compile deliverables: {e}")
        deliverable_md = None

    # ── Final acceptance terminus ─────────────────────────────────────
    # Decision tree (kept here, NOT in compile_deliverables, so callers that
    # invoke compile manually don't accidentally trip the gate):
    #
    #   1. ``auto_final_accept = True``  → straight to ``done``,
    #                                       final_acceptance_status="accepted",
    #                                       by="auto"
    #   2. otherwise                      → ``status=awaiting_final_acceptance``,
    #                                       final_acceptance_status="pending",
    #                                       wait for /final-accept or /final-reject
    auto_accept = bool(db_task and db_task.auto_final_accept)
    if db_task:
        if auto_accept:
            db_task.status = "done"
            db_task.current_stage_id = "done"
            db_task.final_acceptance_status = "accepted"
            db_task.final_acceptance_by = "auto"
            db_task.final_acceptance_at = datetime.utcnow()
        else:
            db_task.status = "awaiting_final_acceptance"
            db_task.current_stage_id = "final_acceptance"
            db_task.final_acceptance_status = "pending"
        await db.flush()

    await complete_trace(trace.trace_id, status="completed")

    summary = {
        "stages_completed": len(results),
        "total_tokens": sum(r.get("tokens", {}).get("total", 0) for r in results),
        "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 6),
        "failed_stages": failed_stages,
    }

    # If force_continue carried us past hard failures, surface that on the task
    # instead of silently reporting a clean completion.
    if failed_stages and db_task:
        db_task.scheduler_last_error = (
            f"{len(failed_stages)} 个阶段失败但被 force_continue 跳过: "
            + ", ".join(f"{f['stage_id']}" for f in failed_stages)
        )[:500]
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    if auto_accept:
        await emit_event("pipeline:auto-completed", {
            "taskId": task_id,
            "title": task_title,
            "stagesCompleted": summary["stages_completed"],
            "totalTokens": summary["total_tokens"],
            "totalCostUsd": summary["total_cost_usd"],
            "traceId": trace.trace_id,
            "hasDeliverable": deliverable_md is not None,
        })
    else:
        await emit_event("pipeline:awaiting-final-acceptance", {
            "taskId": task_id,
            "title": task_title,
            "stagesCompleted": summary["stages_completed"],
            "totalTokens": summary["total_tokens"],
            "totalCostUsd": summary["total_cost_usd"],
            "traceId": trace.trace_id,
            "hasDeliverable": deliverable_md is not None,
            "overallQualityScore": (
                db_task.overall_quality_score if db_task else None
            ),
        })

    # Cross-channel broadcast for critical events
    if db_task:
        try:
            from .notify import broadcast_task_event
            event_name = "completed" if auto_accept else "awaiting_acceptance"
            msg = (
                f"全部 {summary['stages_completed']} 个阶段完成"
                if auto_accept
                else f"全部 {summary['stages_completed']} 个阶段完成，等待最终验收"
            )
            await broadcast_task_event(
                db_task,
                event=event_name,
                message=msg,
                extras={"质量分": f"{round((db_task.overall_quality_score or 0) * 100)}%"},
            )
        except Exception as notify_err:
            logger.debug("[pipeline] cross-channel broadcast failed: %s", notify_err)

    return {
        "ok": True,
        "degraded": bool(failed_stages),
        "failed_stages": failed_stages,
        "results": results,
        "trace_id": trace.trace_id,
        "summary": summary,
    }
