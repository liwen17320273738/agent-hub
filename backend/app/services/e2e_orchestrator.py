"""
End-to-End Orchestrator — the missing link.

Chains the full lifecycle: requirement → pipeline → codegen → build → deploy → preview → notify

This is what makes "send a message from your phone → get a live app" possible.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pipeline import PipelineTask, PipelineArtifact
from .codegen.codegen_agent import _slugify
from .sse import emit_event
from .notify import notify_task_event

logger = logging.getLogger(__name__)

# Gateway / IM 入口在 Phase 2+ 会执行 CodeGen、构建与部署；DAG 阶段若使用 ``full`` 会先完整跑
# development（含再一次 CodeGen）与 testing/reviewing，与 Phase 2 重复且显著拉长耗时。
DEFAULT_GATEWAY_E2E_DAG_TEMPLATE = "e2e_intake"


def _detect_project_type(title: str, description: str, planning_output: str = "") -> str:
    """Auto-detect project type from task content → select template."""
    text = f"{title} {description} {planning_output}".lower()

    miniprogram_kw = ["小程序", "miniprogram", "mini program", "微信小程序", "wechat mini"]
    if any(kw in text for kw in miniprogram_kw):
        return "wechat-miniprogram"

    react_kw = ["react", "nextjs", "next.js"]
    if any(kw in text for kw in react_kw):
        return "react-app"

    vue_kw = ["vue", "nuxt", "element-plus", "vite"]
    if any(kw in text for kw in vue_kw):
        return "vue-app"

    backend_kw = ["api", "后端", "backend", "fastapi", "flask", "django", "数据库"]
    if any(kw in text for kw in backend_kw):
        return "fastapi-backend"

    return "vue-app"


def _detect_deploy_platform(template_id: str, description: str = "") -> str:
    """Choose deploy platform based on project type."""
    text = description.lower()

    if template_id == "wechat-miniprogram":
        return "miniprogram"

    if "cloudflare" in text:
        return "cloudflare"

    return "vercel"


MAX_FIX_RETRIES = 3

# ── Run-loop timeouts ──────────────────────────────────────────────
# Each phase in run_full_e2e gets a total wall-clock budget.  When the
# budget expires the phase is reported as failed (instead of hanging
# silently until the 1800s gateway timeout).
# Phase 1: DAG preamble (planning + design + architecture)
#   - default: each stage has its own STAGE_TIMEOUT below
#   - but the whole DAG must finish within DAG_TIMEOUT
DAG_TIMEOUT: float = float(os.getenv("AGENTHUB_DAG_TIMEOUT", "900"))


async def run_full_e2e(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    auto_deploy: bool = True,
    dag_template: str = DEFAULT_GATEWAY_E2E_DAG_TEMPLATE,
    existing_project_dir: Optional[str] = None,
    pause_for_acceptance: bool = False,
) -> Dict[str, Any]:
    """Execute the FULL end-to-end flow:

    Phase 1: DAG preamble — PRD / UI 规格 / 技术方案（默认 ``e2e_intake``：不含流水线内的 codegen，
    避免与 Phase 2 重复）；可由 ``dag_template`` 改为 ``full`` 等模板。
    Phase 2: Code Generation via Claude Code — writes real files in projects/{slug}
    Phase 3: Build + Test → Fix loop — build, auto-fix up to N times
    Phase 4: Deploy — Vercel / Cloudflare / miniprogram (preview/staging URL), optional via ``auto_deploy``
    Phase 5: Preview + Notify — screenshot
    Phase 5.5: Post-deploy acceptance — optional ``execute_stage(reviewing)`` when preview URL exists

    ``pause_for_acceptance`` (Wave 5 / G1):
        When True, instead of auto-marking the task ``done`` after Phase 5.5,
        we park it at ``awaiting_final_acceptance`` and push an interactive
        acceptance card to the originating IM channel. The user clicks
        接受 / 打回 — accept marks the task done & sends a "已上线" follow-up;
        reject re-runs the chosen stage. This is the toggle the gateway
        flips for Feishu/QQ-originated tasks so deploy → human gate →
        promote becomes a real loop instead of a silent auto-publish.

    Returns a comprehensive result dict.
    """
    # Per-task Redis mutex: prevent concurrent runs on the same task
    # (gateway e2e + manual dag-run triggering simultaneously).
    from .task_lock import TaskLock
    _lock = TaskLock(task_id, ttl=1800)
    if not await _lock.acquire():
        logger.warning("[e2e] Concurrent execution blocked for task %s", task_id)
        return {
            "ok": False,
            "error": "Task is already being executed in another pipeline run",
            "stopped_at": "lock",
        }

    # Suppress the stage→e2e SSE bridge for this context: run_full_e2e emits
    # its own rich e2e:* events, so bridging internal stage:* would duplicate.
    from .sse import suppress_e2e_bridge, restore_e2e_bridge
    _bridge_token = suppress_e2e_bridge()
    try:
        return await _run_e2e_body(
            db, task_id=task_id, task_title=task_title,
            task_description=task_description, auto_deploy=auto_deploy,
            dag_template=dag_template,
            existing_project_dir=existing_project_dir,
            pause_for_acceptance=pause_for_acceptance,
        )
    finally:
        restore_e2e_bridge(_bridge_token)
        await _lock.release()


async def _run_e2e_body(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    auto_deploy: bool = True,
    dag_template: str = DEFAULT_GATEWAY_E2E_DAG_TEMPLATE,
    existing_project_dir: Optional[str] = None,
    pause_for_acceptance: bool = False,
) -> Dict[str, Any]:
    e2e_result: Dict[str, Any] = {
        "task_id": task_id,
        "title": task_title,
        "phases": {},
    }

    db_task = await db.get(PipelineTask, _parse_uuid(task_id))

    async def _notify(event: str, **payload):
        if db_task is None:
            return
        try:
            result = await notify_task_event(db_task, event=event, **payload)
            await emit_event("notify:sent", {
                "taskId": task_id, "event": event, **result.to_dict(),
            })
        except Exception as e:
            logger.error("[e2e] notify %s failed for task %s: %s", event, task_id, e, exc_info=True)

    # Inject existing project context into description so all pipeline agents see it
    effective_description = task_description
    if existing_project_dir:
        from .project_binding import get_project_context
        project_ctx = get_project_context(existing_project_dir)
        if project_ctx:
            effective_description = (
                f"{task_description}\n\n"
                f"## 已有项目上下文（基于现有代码库修改）\n\n{project_ctx}"
            )

    await emit_event("e2e:start", {
        "taskId": task_id,
        "title": task_title,
        "autoDeploy": auto_deploy,
        "existingProject": bool(existing_project_dir),
    })

    await _notify(
        "started",
        message="正在分析需求并规划实现方案",
        extras={"自动部署": "是" if auto_deploy else "否"},
    )

    # ── Pre-flight: log environment state so diagnosis is not guesswork ──
    _pre_flight: Dict[str, str] = {}
    import shutil, sys
    _pre_flight["node"] = shutil.which("node") or "MISSING"
    _pre_flight["pnpm"] = shutil.which("pnpm") or "MISSING"
    _pre_flight["claude"] = shutil.which("claude") or "MISSING (codegen fallback)"
    try:
        import playwright; _pre_flight["playwright"] = "ok"
    except ImportError:
        _pre_flight["playwright"] = "MISSING (QA screenshots will degrade)"
    from ..config import settings
    _pre_flight["vercel_token"] = "set" if settings.vercel_token or os.environ.get("VERCEL_TOKEN") else "MISSING (fallback to local preview)"
    _pre_flight["cloudflare_token"] = "set" if settings.cloudflare_api_token or os.environ.get("CLOUDFLARE_API_TOKEN") else "MISSING"
    logger.info(
        "[e2e] pre-flight for task=%s: %s",
        task_id, {k: v for k, v in _pre_flight.items() if v != "ok"},
    )
    await emit_event("e2e:preflight", {
        "taskId": task_id,
        "checks": _pre_flight,
    })

    # ── Phase 1: DAG preamble (default ``e2e_intake``: planning → design ∥ architecture) ─────
    await emit_event("e2e:phase", {"taskId": task_id, "phase": "design-pipeline", "status": "running"})
    _t_design = time.monotonic()

    from .dag_orchestrator import execute_dag_pipeline

    # The DAG owns its own awaiting_final_acceptance gate (Wave 4 / D),
    # but inside e2e the user's real "is this done?" gate is post-deploy.
    # We temporarily flip auto_final_accept so the DAG does not park,
    # then restore the user's preference when we own the decision below.
    user_auto_final_accept = bool(getattr(db_task, "auto_final_accept", False)) if db_task else False
    if db_task is not None and not user_auto_final_accept:
        db_task.auto_final_accept = True
        await db.flush()

    try:
        pipeline_result = await asyncio.wait_for(
            execute_dag_pipeline(
                db,
                task_id=task_id,
                task_title=task_title,
                task_description=effective_description,
                template=dag_template,
                project_path=existing_project_dir,
            ),
            timeout=DAG_TIMEOUT,
        )
        logger.info(
            "[e2e] phase=dag-preamble template=%s wall_s=%.1f stages_completed=%s",
            dag_template,
            time.monotonic() - _t_design,
            (pipeline_result.get("summary") or {}).get("stagesCompleted", "?"),
        )
    except asyncio.TimeoutError:
        pipeline_result = {
            "ok": False,
            "error": f"DAG timeout after {DAG_TIMEOUT}s",
        }
        await emit_event("e2e:phase", {
            "taskId": task_id, "phase": "design-pipeline", "status": "timed_out",
        })
    finally:
        if db_task is not None and not user_auto_final_accept:
            db_task.auto_final_accept = False
            await db.flush()

    e2e_result["phases"]["design_pipeline"] = {
        "ok": pipeline_result.get("ok", False),
        "stagesCompleted": pipeline_result.get("summary", {}).get("stagesCompleted", 0),
        "traceId": pipeline_result.get("traceId"),
    }

    if not pipeline_result.get("ok"):
        e2e_result["ok"] = False
        e2e_result["stopped_at"] = "design_pipeline"
        e2e_result["error"] = pipeline_result.get("error") or "Design pipeline failed"
        # 将任务状态同步为失败，避免前端看到永久 active/planning 的死锁状态
        try:
            if db_task is not None:
                db_task.status = "failed"
                db_task.scheduler_last_error = e2e_result["error"][:1000]
                await db.commit()
        except Exception as status_err:
            logger.error("[e2e] Failed to update task status on DAG failure for task %s: %s", task_id, status_err, exc_info=True)
            logger.error("[e2e] DAG pipeline_result=%s", pipeline_result.get("error", "unknown"))
        await emit_event("e2e:failed", {"taskId": task_id, "phase": "design-pipeline"})
        await _notify("failed", message="设计阶段失败，请在控制台查看详情",
                      extras={"阶段": "design-pipeline"})
        return e2e_result

    await emit_event("e2e:phase", {"taskId": task_id, "phase": "design-pipeline", "status": "done"})
    await _notify(
        "progress",
        message="需求与架构设计完成，开始生成代码",
        extras={"已完成阶段": pipeline_result.get("summary", {}).get("stagesCompleted", 0)},
    )

    outputs: Dict[str, str] = {}
    for stage_result in pipeline_result.get("results", []):
        sid = stage_result.get("stageId", "")
        content = stage_result.get("content", "")
        if sid and content:
            outputs[sid] = content

    # ── Phase 2: Code Generation via Claude Code ────────────────────
    await emit_event("e2e:phase", {"taskId": task_id, "phase": "codegen", "status": "running"})
    _t_codegen = time.monotonic()

    template_id = _detect_project_type(
        task_title, task_description, outputs.get("planning", ""),
    )

    from .codegen import CodeGenAgent
    codegen = CodeGenAgent()

    codegen_result = await codegen.generate_from_pipeline(
        task_id=task_id,
        task_title=task_title,
        pipeline_outputs=outputs,
        template_id=template_id if not existing_project_dir else None,
        use_claude_code=True,
        existing_project_dir=existing_project_dir,
    )
    logger.info(
        "[e2e] phase=codegen wall_s=%.1f ok=%s engine=%s files=%s",
        time.monotonic() - _t_codegen,
        codegen_result.get("ok"),
        codegen_result.get("engine"),
        codegen_result.get("total_files", 0),
    )

    e2e_result["phases"]["codegen"] = {
        "ok": codegen_result.get("ok", False),
        "engine": codegen_result.get("engine", "unknown"),
        "template": template_id,
        "filesWritten": codegen_result.get("total_files", 0),
        "projectDir": codegen_result.get("project_dir", ""),
    }

    if not codegen_result.get("ok"):
        e2e_result["ok"] = False
        e2e_result["stopped_at"] = "codegen"
        e2e_result["error"] = codegen_result.get("error", "Code generation failed")
        # 将任务状态同步为失败，避免前端看到永久 active 的死锁状态
        try:
            if db_task is not None:
                db_task.status = "failed"
                db_task.scheduler_last_error = e2e_result["error"][:1000]
                await db.commit()
        except Exception as status_err:
            logger.error("[e2e] Failed to update task status on codegen failure for task %s: %s", task_id, status_err, exc_info=True)
            logger.error("[e2e] codegen error=%s", codegen_result.get("error", "unknown"))
        await emit_event("e2e:failed", {"taskId": task_id, "phase": "codegen"})
        await _notify(
            "failed",
            message="代码生成失败",
            extras={
                "引擎": codegen_result.get("engine", "unknown"),
                "错误": (codegen_result.get("error", "") or "")[:200],
            },
        )
        return e2e_result

    project_dir = codegen_result["project_dir"]
    await emit_event("e2e:phase", {
        "taskId": task_id, "phase": "codegen", "status": "done",
        "engine": codegen_result.get("engine"),
        "filesWritten": codegen_result.get("total_files", 0),
    })
    await _notify(
        "progress",
        message="代码生成完成，开始构建验证",
        extras={"引擎": codegen_result.get("engine", "unknown"), "文件数": codegen_result.get("total_files", 0)},
    )

    # ── Phase 3: Build + Test → Fix Loop ────────────────────────────
    await emit_event("e2e:phase", {"taskId": task_id, "phase": "build-test", "status": "running"})

    from .codegen.templates import get_template
    template = get_template(template_id)
    build_cmd = template.get("build_cmd", "") if template else ""

    await _notify(
        "progress",
        message="正在构建与测试代码",
        extras={"构建命令": build_cmd or "（未定义）"},
    )
    _t_build = time.monotonic()

    build_test_result: Dict[str, Any] = {"ok": True, "skipped": not build_cmd, "attempts": 0}

    if build_cmd:
        for attempt in range(1, MAX_FIX_RETRIES + 1):
            build_test_result["attempts"] = attempt

            await emit_event("e2e:build-progress", {
                "taskId": task_id,
                "attempt": attempt,
                "maxRetries": MAX_FIX_RETRIES,
                "status": "running",
                "message": f"Build attempt {attempt}/{MAX_FIX_RETRIES}",
            })

            build_output = await codegen.run_build(project_dir, build_cmd)
            build_test_result["build_output"] = build_output.get("output", "")[:1000]

            if build_output.get("ok"):
                build_test_result["ok"] = True
                build_test_result["fixed_on_attempt"] = attempt if attempt > 1 else None
                await emit_event("e2e:build-progress", {
                    "taskId": task_id,
                    "attempt": attempt,
                    "maxRetries": MAX_FIX_RETRIES,
                    "status": "done",
                    "message": "Build passed" if attempt == 1 else f"Build passed after auto-fix",
                })
                break

            await emit_event("e2e:build-failed", {
                "taskId": task_id,
                "attempt": attempt,
                "maxRetries": MAX_FIX_RETRIES,
                "errorSnippet": build_output.get("output", "")[:500],
            })

            if attempt >= MAX_FIX_RETRIES:
                build_test_result["ok"] = False
                build_test_result["error"] = f"Build failed after {MAX_FIX_RETRIES} attempts"
                break

            build_log_path = os.path.join(project_dir, "build.log")
            fix_result = await codegen.auto_fix(
                task_id=task_id,
                project_dir=project_dir,
                build_log_path=build_log_path,
                attempt=attempt,
            )

            await emit_event("e2e:auto-fix", {
                "taskId": task_id,
                "attempt": attempt,
                "fixOk": fix_result.get("ok", False),
                "message": f"Auto-fix attempt {attempt}: {'ok' if fix_result.get('ok') else 'failed'}",
            })

            if not fix_result.get("ok"):
                build_test_result["ok"] = False
                build_test_result["error"] = f"Auto-fix failed on attempt {attempt}"
                break

    e2e_result["phases"]["build_test"] = build_test_result
    logger.info(
        "[e2e] phase=build-test wall_s=%.1f ok=%s attempts=%s skipped=%s",
        time.monotonic() - _t_build,
        build_test_result.get("ok"),
        build_test_result.get("attempts"),
        build_test_result.get("skipped"),
    )

    if not build_test_result.get("ok"):
        if build_test_result.get("skipped"):
            # F6: on auto-deploy golden path, skipped build is not acceptable.
            e2e_result["ok"] = False
            e2e_result["stopped_at"] = "build_test"
            e2e_result["error"] = "No build command defined for this project template; cannot verify code quality"
            await emit_event("e2e:failed", {"taskId": task_id, "phase": "build-test", "reason": "build_skipped"})
            await _notify("failed", message="构建跳过：未定义构建命令，无法验证代码质量")
            return e2e_result
        else:
            e2e_result["ok"] = False
            e2e_result["stopped_at"] = "build_test"
            e2e_result["error"] = build_test_result.get("error", "Build failed")
            await emit_event("e2e:failed", {"taskId": task_id, "phase": "build-test"})
            await _notify(
                "failed",
                message="构建/测试失败，自动修复重试已用尽",
                extras={"重试次数": build_test_result.get("attempts", 0)},
            )
            return e2e_result

    await emit_event("e2e:phase", {
        "taskId": task_id, "phase": "build-test", "status": "done",
        "attempts": build_test_result.get("attempts", 0),
    })
    await _notify(
        "progress",
        message="构建验证通过",
        extras={"尝试次数": build_test_result.get("attempts", 0)},
    )

    # ── Write code artifacts (source_manifest + build.log) to DB ────
    # If artifacts fail to persist, the delivery contract cannot verify
    # code generation: treat as a codegen phase failure instead of silently
    # continuing with no evidence.
    try:
        from .artifact_writer import write_code_artifacts
        await write_code_artifacts(db, task_id=task_id, project_dir=project_dir, agent_name="Agent-developer")
        logger.info("[e2e] write_code_artifacts done for task %s", task_id)
    except Exception as e:
        logger.error("[e2e] write_code_artifacts failed for task %s: %s", task_id, e, exc_info=True)
        await emit_event("e2e:phase", {
            "taskId": task_id, "phase": "codegen", "status": "degraded",
            "error": f"代码工件写入失败: {e}",
        })
        await _notify("failed", message="代码构件写入失败，阶段标记降级")
        e2e_result["phases"]["codegen"] = {
            "ok": False, "error": f"write_code_artifacts failed: {e}",
        }
        e2e_result["ok"] = False
        return e2e_result

    # ── Phase 3.5: Real QA execution → test_report / test_log evidence ──
    # The build loop above only proves the project compiles. The delivery
    # contract (verify_delivery_evidence) additionally requires test_report
    # and test_log artifacts. QaExecutor runs install/build/test + browser
    # smoke and persists structured evidence. QA is best-effort here: missing
    # tooling (e.g. playwright) must NOT regress the deploy-only golden path,
    # so failures are recorded but do not stop the flow.
    qa_summary: Dict[str, Any] = {"ok": False, "ran": False}
    try:
        from .qa_executor import QaExecutor
        from .artifact_writer import write_qa_artifacts

        await emit_event("e2e:phase", {"taskId": task_id, "phase": "qa", "status": "running"})
        await _notify("progress", message="正在运行真实测试与冒烟检查")

        qa = QaExecutor(project_dir)
        qa_result = await qa.run_full_qa()
        qa_summary = {
            "ok": bool(qa_result.get("ok")),
            "ran": True,
            "blocked": bool(qa_result.get("blocked")),
            "failed_step": qa_result.get("failed_step"),
        }

        # Always persist whatever evidence QA produced (test_report/test_log/...)
        try:
            qa_arts = await write_qa_artifacts(db, task_id, project_dir, qa_result)
            logger.info("[e2e] write_qa_artifacts wrote %d artifacts for task %s", len(qa_arts), task_id)
        except Exception as we:
            logger.error("[e2e] write_qa_artifacts failed for task %s: %s", task_id, we, exc_info=True)

        await emit_event("e2e:phase", {
            "taskId": task_id, "phase": "qa",
            "status": "done" if qa_summary["ok"] else "degraded",
            "blocked": qa_summary["blocked"],
            "failedStep": qa_summary["failed_step"],
        })
        if not qa_summary["ok"]:
            logger.warning(
                "[e2e] QA did not fully pass for task %s (blocked=%s, failed_step=%s) — continuing to deploy",
                task_id, qa_summary["blocked"], qa_summary["failed_step"],
            )
    except Exception as qa_err:
        logger.error("[e2e] QA execution error for task %s: %s — continuing", task_id, qa_err, exc_info=True)
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "qa", "status": "degraded"})

    e2e_result["phases"]["qa"] = qa_summary

    # ── Phase 4: Deploy ─────────────────────────────────────────────
    deploy_result: Dict[str, Any] = {"ok": False, "skipped": True}

    if auto_deploy:
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "deploy", "status": "running"})
        await _notify(
            "progress",
            message="正在部署到线上环境",
            extras={"平台": _detect_deploy_platform(template_id, task_description)},
        )

        platform = _detect_deploy_platform(template_id, task_description)
        deploy_result = await _auto_deploy(
            task_id=task_id,
            project_dir=project_dir,
            project_name=_slugify(task_title),
            platform=platform,
            template_id=template_id,
        )
        deploy_result["platform"] = platform

        if deploy_result.get("ok"):
            artifact = PipelineArtifact(
                task_id=_parse_uuid(task_id),
                artifact_type="deployment",
                name=f"部署 — {platform}",
                content=f"URL: {deploy_result.get('url', 'N/A')}\nPlatform: {platform}",
                stage_id="deployment",
            )
            db.add(artifact)
            await db.flush()

        await emit_event("e2e:phase", {
            "taskId": task_id,
            "phase": "deploy",
            "status": "done" if deploy_result.get("ok") else "failed",
            "url": deploy_result.get("url", ""),
            "provider": deploy_result.get("provider", platform),
            "healthStatus": deploy_result.get("health_status"),
        })

        if not deploy_result.get("ok"):
            e2e_result["phases"]["deploy"] = deploy_result
            e2e_result["ok"] = False
            e2e_result["stopped_at"] = "deploy"
            e2e_result["error"] = deploy_result.get("error", "Deploy failed")
            await emit_event("e2e:failed", {
                "taskId": task_id,
                "phase": "deploy",
                "error": e2e_result["error"],
            })
            await _notify(
                "failed",
                message="部署失败，未生成可验收的预览链接",
                extras={"平台": platform, "错误": str(e2e_result["error"])[:200]},
            )
            return e2e_result
    elif pause_for_acceptance:
        e2e_result["phases"]["deploy"] = deploy_result
        e2e_result["ok"] = False
        e2e_result["stopped_at"] = "deploy"
        e2e_result["error"] = "auto_deploy disabled; final acceptance requires a preview URL"
        await emit_event("e2e:failed", {
            "taskId": task_id,
            "phase": "deploy",
            "error": e2e_result["error"],
        })
        return e2e_result

    e2e_result["phases"]["deploy"] = deploy_result

    # ── Phase 5: Preview + Notify ───────────────────────────────────
    preview_url = deploy_result.get("url", "")
    preview_result: Dict[str, Any] = {"ok": True, "skipped": not preview_url}

    if not preview_url and auto_deploy:
        e2e_result["phases"]["preview"] = {
            "ok": False,
            "skipped": False,
            "error": "Deploy succeeded without a preview URL",
        }
        e2e_result["ok"] = False
        e2e_result["stopped_at"] = "preview"
        e2e_result["error"] = "Deploy succeeded without a preview URL"
        await emit_event("e2e:failed", {
            "taskId": task_id,
            "phase": "preview",
            "error": e2e_result["error"],
        })
        return e2e_result

    if preview_url:
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "preview", "status": "running"})
        await _notify(
            "progress",
            message="正在截取部署预览截图",
            extras={"URL": preview_url},
        )

        # Use existing local screenshot from LocalPreview if available;
        # otherwise capture one via StealthBrowser (Playwright) — NOT
        # PreviewService (which uses Puppeteer and blocks localhost).
        screenshot_path: str = deploy_result.get("screenshot_path") or ""
        screenshot_ok = bool(screenshot_path) and os.path.isfile(screenshot_path)

        if not screenshot_ok and preview_url:
            try:
                from .stealth_browser import StealthBrowser as _SB
                ss_dir = deploy_result.get("screenshot_dir") or "/tmp/agent-hub-previews"
                os.makedirs(ss_dir, exist_ok=True)
                ss_path = os.path.join(ss_dir, f"{task_id}.png")
                _b = _SB()
                await _b.open(headless=True, viewport="1280x720")
                nav = await _b.navigate(preview_url, wait_until="networkidle")
                if nav.get("success"):
                    await _b.screenshot(path=ss_path)
                    screenshot_path = ss_path
                    screenshot_ok = True
                await _b.close()
            except Exception as ss_e:
                logger.error("[e2e] StealthBrowser screenshot failed for task %s, url=%s: %s", task_id, preview_url, ss_e, exc_info=True)
                screenshot_ok = False
                screenshot_path = ""

        preview_result = {
            "ok": screenshot_ok,
            "screenshotOk": screenshot_ok,
            "screenshotPath": screenshot_path if screenshot_ok else "",
            "error": "" if screenshot_ok else "deploy screenshot unavailable (LocalPreview did not capture it and StealthBrowser failed)",
        }

        e2e_result["phases"]["preview"] = preview_result
        await emit_event("e2e:phase", {
            "taskId": task_id,
            "phase": "preview",
            "status": "done" if preview_result.get("ok") else "failed",
        })
        if not preview_result.get("ok"):
            e2e_result["ok"] = False
            e2e_result["stopped_at"] = "preview"
            e2e_result["error"] = preview_result.get("error", "Preview verification failed")
            await emit_event("e2e:failed", {
                "taskId": task_id,
                "phase": "preview",
                "error": e2e_result["error"],
            })
            await _notify(
                "failed",
                message="预览验证失败，未进入验收",
                url=preview_url,
                extras={"错误": str(e2e_result["error"])[:200]},
            )
            return e2e_result

    else:
        e2e_result["phases"]["preview"] = preview_result

    # ── Write deploy artifacts (preview_url, screenshot, ops_runbook) to DB ──
    if deploy_result.get("ok"):
        try:
            from .artifact_writer import write_deploy_artifacts
            deploy_payload = dict(deploy_result)
            if preview_result.get("screenshotPath"):
                deploy_payload["screenshot_path"] = preview_result["screenshotPath"]
            await write_deploy_artifacts(db, task_id=task_id, project_dir=project_dir, deploy_result=deploy_payload)
            logger.info("[e2e] write_deploy_artifacts done for task %s", task_id)
        except Exception as e:
            logger.error("[e2e] write_deploy_artifacts failed for task %s: %s", task_id, e, exc_info=True)
            await emit_event("e2e:phase", {
                "taskId": task_id, "phase": "deploy", "status": "degraded",
                "error": f"部署工件写入失败: {e}",
            })
            await _notify("failed", message="部署构件写入失败，阶段标记降级")
            deploy_result = dict(deploy_result)
            deploy_result["ok"] = False
            deploy_result["error"] = f"write_deploy_artifacts failed: {e}"

    # ── Phase 5.5: Post-deploy Acceptance (evidence-based) ───────────
    # Re-invoke the reviewing stage with the live URL + screenshot baked
    # into previous_outputs so the acceptance-agent can use browser_*
    # tools to do real E2E validation, not just paper review.
    acceptance_result: Dict[str, Any] = {"ok": True, "skipped": True}
    if preview_url:
        await emit_event("e2e:phase", {
            "taskId": task_id, "phase": "acceptance", "status": "running",
        })
        await _notify(
            "progress",
            message="AI 正在对上线内容做最终验收",
            extras={"URL": preview_url},
        )
        try:
            from .pipeline_engine import execute_stage

            evidence_block = (
                f"## 已上线预览（请使用 browser_* 工具实际访问验证）\n"
                f"- 预览 URL: {preview_url}\n"
                f"- 平台: {deploy_result.get('platform', 'unknown')}\n"
            )
            if preview_result.get("screenshotPath"):
                evidence_block += f"- 首页截图本地路径: {preview_result['screenshotPath']}\n"

            acceptance_outputs = dict(outputs)
            acceptance_outputs["deployment"] = (
                acceptance_outputs.get("deployment", "") + "\n\n" + evidence_block
            ).strip()

            acc = await execute_stage(
                db,
                task_id=task_id,
                task_title=task_title,
                task_description=effective_description,
                stage_id="reviewing",
                previous_outputs=acceptance_outputs,
            )
            acceptance_result = {
                "ok": bool(acc.get("ok")),
                "verdict": "APPROVED" if "APPROVED" in (acc.get("content") or "")[:200] else "REJECTED",
                "report": (acc.get("content") or "")[:4000],
                "tokens": acc.get("tokens"),
                "cost_usd": acc.get("cost_usd"),
            }
        except Exception as e:
            logger.error("[e2e] post-deploy acceptance failed for task %s: %s", task_id, e, exc_info=True)
            acceptance_result = {"ok": False, "skipped": False, "error": str(e)}

        e2e_result["phases"]["acceptance"] = acceptance_result
        await emit_event("e2e:phase", {
            "taskId": task_id, "phase": "acceptance",
            "status": "done" if acceptance_result.get("ok") else "failed",
            "verdict": acceptance_result.get("verdict"),
        })
    else:
        e2e_result["phases"]["acceptance"] = acceptance_result

    if preview_url:
        verdict_label = acceptance_result.get("verdict", "")
        notify_extras = {"平台": deploy_result.get("platform", "")}
        if verdict_label:
            notify_extras["验收"] = verdict_label
        await _notify(
            "preview",
            message="预览已就绪，回复「通过」即上线，或「修改：xxx」反馈",
            url=preview_url,
            extras=notify_extras,
        )

    # ── Done ────────────────────────────────────────────────────────
    optional_skips = {"acceptance"} if not preview_url else set()
    all_ok = all(
        phase.get("ok", False)
        or (name in optional_skips and phase.get("skipped", False))
        for name, phase in e2e_result["phases"].items()
    )
    e2e_result["ok"] = all_ok
    e2e_result["url"] = preview_url

    # Wave 5 / G1: when the gateway asked us to pause, hand off to the
    # human acceptance terminus instead of auto-publishing. The DAG
    # orchestrator may have already moved the task into a terminal state
    # (because we let it run to completion above); here we explicitly
    # override it so we own the decision.
    # ── Phase 5.8: Delivery Contract Gate (F1) ─────────────────────
    # Before auto-accepting, verify that the delivery evidence actually
    # exists (real test passing, real preview URL with healthy status,
    # real acceptance evidence).  This is the hard gate that prevents
    # "trust-killer" silent OK where we mark a task done without real
    # proof of working software.
    contract_pass = True
    if db_task and all_ok and not pause_for_acceptance:
        try:
            from .delivery_contract import verify_delivery_evidence
            ev = await verify_delivery_evidence(db, db_task)
            contract_pass = ev.ok
            if not contract_pass:
                logger.error(
                    "[e2e] Delivery contract BLOCKED auto-accept for task %s: %s",
                    task_id, ev.summary,
                )
                # Do NOT mark task as done — downgrade to awaiting evidence
                db_task.status = "awaiting_evidence"
                db_task.current_stage_id = "final_acceptance"
                db_task.final_acceptance_status = "pending"
                await db.flush()
                await emit_event("e2e:contract-blocked", {
                    "taskId": task_id,
                    "summary": ev.summary,
                    "missing": list(ev.missing),
                })
        except Exception as contract_err:
            # Fail-closed: if we cannot verify the delivery contract, do NOT
            # auto-publish. Downgrade to awaiting_evidence so a human reviews
            # rather than silently shipping unverified work.
            logger.error(
                "[e2e] Delivery contract check errored for task %s — failing closed (awaiting evidence): %s",
                task_id, contract_err, exc_info=True,
            )
            contract_pass = False
            if db_task:
                db_task.status = "awaiting_evidence"
                db_task.current_stage_id = "final_acceptance"
                db_task.final_acceptance_status = "pending"
                await db.flush()
                await emit_event("e2e:contract-blocked", {
                    "taskId": task_id,
                    "summary": "交付证据校验异常，已转入人工复核",
                    "missing": [],
                })
    else:
        contract_pass = True

    pause_now = pause_for_acceptance and all_ok and bool(db_task) and contract_pass

    if db_task and all_ok and not pause_now and contract_pass:
        db_task.status = "done"
        # Auto-publish path: stamp the auto-acceptance so the dashboard's
        # final-acceptance banner doesn't blink for already-done tasks.
        if not (db_task.final_acceptance_status or "").strip():
            from datetime import datetime as _dt
            db_task.final_acceptance_status = "accepted"
            db_task.final_acceptance_by = "auto"
            db_task.final_acceptance_at = _dt.utcnow()
        await db.flush()
    elif pause_now:
        from datetime import datetime as _dt
        db_task.status = "awaiting_final_acceptance"
        db_task.current_stage_id = "final_acceptance"
        db_task.final_acceptance_status = "pending"
        db_task.final_acceptance_at = None
        db_task.final_acceptance_by = None
        await db.flush()
        e2e_result["awaitingFinalAcceptance"] = True
        await emit_event("pipeline:awaiting-final-acceptance", {
            "taskId": task_id,
            "title": task_title,
            "url": preview_url,
            "stagesCompleted": pipeline_result.get("summary", {}).get("stagesCompleted", 0),
            "stagesTotal": pipeline_result.get("summary", {}).get("stagesTotal", 0),
            "overallQualityScore": getattr(db_task, "overall_quality_score", None),
            "previewReady": bool(preview_url),
        })

    await emit_event("e2e:complete", {
        "taskId": task_id,
        "ok": all_ok,
        "url": preview_url,
        "engine": codegen_result.get("engine", "unknown"),
        "phases": {k: v.get("ok", False) for k, v in e2e_result["phases"].items()},
        "awaitingAcceptance": pause_now,
    })

    if all_ok and pause_now:
        # Push the interactive acceptance card with preview URL + score.
        await _notify(
            "awaiting_acceptance",
            message="预览已就绪，请验收：通过 / 打回重做",
            url=preview_url,
            extras={
                "代码生成": codegen_result.get("engine", "unknown"),
                "质量分": getattr(db_task, "overall_quality_score", None),
            },
        )
    elif all_ok:
        await _notify(
            "completed",
            message="项目已上线，开始体验吧",
            url=preview_url,
            extras={"代码生成": codegen_result.get("engine", "unknown")},
        )

    return e2e_result


async def _auto_deploy(
    *,
    task_id: str,
    project_dir: str,
    project_name: str,
    platform: str,
    template_id: str,
) -> Dict[str, Any]:
    """Deploy to the detected platform."""
    from ..config import settings

    if platform == "vercel":
        token = settings.vercel_token or os.environ.get("VERCEL_TOKEN", "")
        if token:
            from .deploy.vercel import deploy_to_vercel
            result = await deploy_to_vercel(
                project_dir=project_dir,
                project_name=project_name,
                token=token,
                production=False,
            )
            if result.get("ok"):
                result["provider"] = "vercel"
                return result
            logger.warning("[e2e] Vercel deploy failed for task %s (%s); falling back to local preview", task_id, result.get("error", "unknown"))

        # Fallback to local preview
        from .deploy.local_preview import LocalPreview
        local = LocalPreview(project_dir)
        res = await local.deploy()
        if not res.ok:
            local._cleanup()
            return {
                "ok": False,
                "error": f"Vercel not available and local preview failed: {res.error}",
                "skipped": False,
                "url": res.url or "",
            }
        local.detach()
        return {
            "ok": True,
            "provider": "local",
            "url": res.url,
            "port_used": res.port_used,
            "health_status": res.health_status,
            "screenshot_path": res.screenshot_path or "",
            "deployed_at": res.deployed_at,
        }

    if platform == "cloudflare":
        token = settings.cloudflare_api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account_id = settings.cloudflare_account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account_id:
            return {"ok": False, "error": "CLOUDFLARE credentials not configured", "skipped": True}

        from .deploy.cloudflare import deploy_to_cloudflare
        return await deploy_to_cloudflare(
            project_dir=project_dir,
            project_name=project_name,
            api_token=token,
            account_id=account_id,
        )

    if platform == "miniprogram":
        app_id = settings.wechat_mp_appid or os.environ.get("WECHAT_MP_APPID", "")
        key_path = settings.wechat_mp_private_key_path or os.environ.get("WECHAT_MP_PRIVATE_KEY_PATH", "")
        if not app_id or not key_path:
            return {"ok": False, "error": "WeChat MP credentials not configured", "skipped": True}

        from .deploy.miniprogram import deploy_miniprogram
        return await deploy_miniprogram(
            project_dir=project_dir,
            app_id=app_id,
            private_key_path=key_path,
        )

    return {"ok": False, "error": f"Unknown platform: {platform}", "skipped": True}


def _parse_uuid(task_id: str):
    import uuid
    try:
        return uuid.UUID(task_id)
    except ValueError:
        return task_id
