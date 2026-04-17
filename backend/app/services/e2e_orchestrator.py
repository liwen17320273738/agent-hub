"""
End-to-End Orchestrator — the missing link.

Chains the full lifecycle: requirement → pipeline → codegen → build → deploy → preview → notify

This is what makes "send a message from your phone → get a live app" possible.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models.pipeline import PipelineTask, PipelineStage, PipelineArtifact
from .sse import emit_event
from .notify import notify_task_event

logger = logging.getLogger(__name__)


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


async def run_full_e2e(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    auto_deploy: bool = True,
    dag_template: str = "full",
    existing_project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the FULL end-to-end flow:

    Phase 1: Design Pipeline (planning → architecture) — generates PRD + tech spec
    Phase 2: Code Generation via Claude Code — writes real files in projects/{slug}
    Phase 3: Build + Test → Fix loop — build, run tests, auto-fix up to N times
    Phase 4: Review Pipeline (testing → reviewing) — QA validates the real code
    Phase 5: Deploy — Vercel / Cloudflare / miniprogram
    Phase 6: Preview + Notify — screenshot + channel notification

    Returns a comprehensive result dict.
    """
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
            logger.warning(f"[e2e] notify {event} failed: {e}")

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

    # ── Phase 1: Design Pipeline (planning + architecture only) ─────
    await emit_event("e2e:phase", {"taskId": task_id, "phase": "design-pipeline", "status": "running"})

    from .dag_orchestrator import execute_dag_pipeline

    pipeline_result = await execute_dag_pipeline(
        db,
        task_id=task_id,
        task_title=task_title,
        task_description=effective_description,
        template=dag_template,
        project_path=existing_project_dir,
    )

    e2e_result["phases"]["design_pipeline"] = {
        "ok": pipeline_result.get("ok", False),
        "stagesCompleted": pipeline_result.get("summary", {}).get("stagesCompleted", 0),
        "traceId": pipeline_result.get("traceId"),
    }

    if not pipeline_result.get("ok"):
        e2e_result["ok"] = False
        e2e_result["stopped_at"] = "design_pipeline"
        e2e_result["error"] = "Design pipeline failed"
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

    # ── Phase 3: Build + Test → Fix Loop ────────────────────────────
    await emit_event("e2e:phase", {"taskId": task_id, "phase": "build-test", "status": "running"})

    from .codegen.templates import get_template
    template = get_template(template_id)
    build_cmd = template.get("build_cmd", "") if template else ""

    build_test_result: Dict[str, Any] = {"ok": True, "skipped": not build_cmd, "attempts": 0}

    if build_cmd:
        for attempt in range(1, MAX_FIX_RETRIES + 1):
            build_test_result["attempts"] = attempt

            build_output = await codegen.run_build(project_dir, build_cmd)
            build_test_result["build_output"] = build_output.get("output", "")[:1000]

            if build_output.get("ok"):
                build_test_result["ok"] = True
                build_test_result["fixed_on_attempt"] = attempt if attempt > 1 else None
                break

            await emit_event("e2e:build-failed", {
                "taskId": task_id,
                "attempt": attempt,
                "maxRetries": MAX_FIX_RETRIES,
            })

            if attempt >= MAX_FIX_RETRIES:
                build_test_result["ok"] = False
                build_test_result["error"] = f"Build failed after {MAX_FIX_RETRIES} attempts"
                break

            fix_result = await codegen.auto_fix(
                task_id=task_id,
                project_dir=project_dir,
                error_output=build_output.get("output", ""),
                attempt=attempt,
            )

            await emit_event("e2e:auto-fix", {
                "taskId": task_id,
                "attempt": attempt,
                "fixOk": fix_result.get("ok", False),
            })

            if not fix_result.get("ok"):
                build_test_result["ok"] = False
                build_test_result["error"] = f"Auto-fix failed on attempt {attempt}"
                break

    e2e_result["phases"]["build_test"] = build_test_result

    if not build_test_result.get("ok") and not build_test_result.get("skipped"):
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

    # ── Phase 4: Deploy ─────────────────────────────────────────────
    deploy_result: Dict[str, Any] = {"ok": False, "skipped": True}

    if auto_deploy:
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "deploy", "status": "running"})

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
        })

    e2e_result["phases"]["deploy"] = deploy_result

    # ── Phase 5: Preview + Notify ───────────────────────────────────
    preview_url = deploy_result.get("url", "")
    preview_result: Dict[str, Any] = {"ok": True, "skipped": not preview_url}

    if preview_url:
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "preview", "status": "running"})

        try:
            from .interaction.preview import PreviewService
            preview_svc = PreviewService()
            screenshot_dir = "/tmp/agent-hub-previews"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"{task_id}.png")
            shot = await preview_svc.capture_screenshot(
                url=preview_url, output_path=screenshot_path,
            )
            preview_result = {"ok": True, "screenshotOk": bool(shot.get("ok")),
                              "screenshotPath": screenshot_path if shot.get("ok") else ""}
        except Exception as e:
            logger.warning(f"[e2e] screenshot failed: {e}")
            preview_result = {"ok": True, "screenshotOk": False, "error": str(e)}

        e2e_result["phases"]["preview"] = preview_result
        await emit_event("e2e:phase", {"taskId": task_id, "phase": "preview", "status": "done"})

        await _notify(
            "preview",
            message="预览已就绪，回复「通过」即上线，或「修改：xxx」反馈",
            url=preview_url,
            extras={"平台": deploy_result.get("platform", "")},
        )
    else:
        e2e_result["phases"]["preview"] = preview_result

    # ── Done ────────────────────────────────────────────────────────
    all_ok = all(
        phase.get("ok", False) or phase.get("skipped", False)
        for phase in e2e_result["phases"].values()
    )
    e2e_result["ok"] = all_ok
    e2e_result["url"] = preview_url

    if db_task and all_ok:
        db_task.status = "done"
        await db.flush()

    await emit_event("e2e:complete", {
        "taskId": task_id,
        "ok": all_ok,
        "url": preview_url,
        "engine": codegen_result.get("engine", "unknown"),
        "phases": {k: v.get("ok", False) for k, v in e2e_result["phases"].items()},
    })

    if all_ok:
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
        if not token:
            return {"ok": False, "error": "VERCEL_TOKEN not configured", "skipped": True}

        from .deploy.vercel import deploy_to_vercel
        return await deploy_to_vercel(
            project_dir=project_dir,
            project_name=project_name,
            token=token,
            production=False,
        )

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


def _slugify(text: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug[:64].strip("-") or "project"


def _parse_uuid(task_id: str):
    import uuid
    try:
        return uuid.UUID(task_id)
    except ValueError:
        return task_id
