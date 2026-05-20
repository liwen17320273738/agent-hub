"""
Artifact writer — bridge between pipeline engine stage output and v2 TaskArtifact DB.

Maps stage_id to artifact_type, creates/versions the TaskArtifact row,
and triggers manifest refresh. Controlled by config.artifact_store_v2 flag.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.task_artifact import TaskArtifact

logger = logging.getLogger(__name__)

STAGE_TO_ARTIFACT: dict[str, str] = {
    "planning":     "prd",
    "design":       "ui_spec",
    "architecture": "architecture",
    "development":  "code_link",
    "testing":      "test_report",
    "reviewing":    "acceptance",
    "deployment":   "ops_runbook",
}

AUX_STAGE_LABELS: dict[str, str] = {
    "security-review": "安全审查",
    "data-modeling": "数据建模",
    "marketing-launch": "上线运营",
    "finance-review": "财务评估",
    "legal-review": "法务审查",
}

STAGE_TO_DOC_FILE: dict[str, str] = {
    "planning":     "docs/01-prd.md",
    "design":       "docs/02-ui-spec.md",
    "architecture": "docs/03-architecture.md",
    "development":  "docs/04-implementation-notes.md",
    "testing":      "docs/05-test-report.md",
    "reviewing":    "docs/06-acceptance.md",
    "deployment":   "docs/07-ops-runbook.md",
}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _brief_from_planning(title: str, content: str) -> str:
    """Short brief for requirements tab; PRD row holds full planning output."""
    head = (content or "").strip()
    cap = 4500
    if len(head) > cap:
        head = head[:cap] + "\n\n…(完整 PRD 见「PRD」工件与 docs/01-prd.md)"
    return f"# 需求简报 — {title}\n\n{head}\n"


async def _append_auxiliary_attachment(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    section_title: str,
    content: str,
    agent_name: Optional[str] = None,
) -> TaskArtifact:
    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
    existing = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.artifact_type == "attachment",
                TaskArtifact.is_latest.is_(True),
            )
        )
    )
    prev = existing.scalar_one_or_none()
    base = (prev.content if prev else "# 附属交付物（安全 / 数据 / 运营 / 财务 / 法务）\n")
    section = f"\n\n## {section_title} (`{stage_id}`)\n\n{(content or '').strip()}\n"
    return await _write_one_artifact(
        db, task_id, stage_id, "attachment", base + section,
        "docs/auxiliary-stages.md", agent_name,
    )


async def _write_one_artifact(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    artifact_type: str,
    content: str,
    storage_path: str,
    agent_name: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> TaskArtifact:
    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id

    existing = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.artifact_type == artifact_type,
                TaskArtifact.is_latest.is_(True),
            )
        )
    )
    current = existing.scalar_one_or_none()
    new_version = (current.version + 1) if current else 1

    if current:
        current.is_latest = False
        await db.flush()

    art = TaskArtifact(
        task_id=tid,
        stage_id=stage_id,
        artifact_type=artifact_type,
        title=artifact_type,
        content=content,
        content_hash=_content_hash(content),
        storage_path=storage_path,
        metadata_json=metadata_json or {},
        version=new_version,
        is_latest=True,
        status="active",
        created_by_agent=agent_name,
    )
    db.add(art)
    await db.flush()
    logger.info(
        "[artifact_writer] Wrote %s v%d for task %s",
        artifact_type, new_version, task_id,
    )
    return art


async def write_artifact_v2(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    content: str,
    agent_name: Optional[str] = None,
) -> Optional[TaskArtifact]:
    if not settings.artifact_store_v2:
        return None

    artifact_type = STAGE_TO_ARTIFACT.get(stage_id)
    if not artifact_type:
        return None

    art = await _write_one_artifact(
        db, task_id, stage_id, artifact_type, content,
        STAGE_TO_DOC_FILE.get(stage_id, ""), agent_name,
    )
    try:
        from .manifest_sync import trigger_manifest_refresh
        await trigger_manifest_refresh(str(task_id), db=db)
    except Exception:
        pass
    return art


async def write_stage_artifacts_v2(
    db: AsyncSession,
    task_id: str,
    task_title: str,
    stage_id: str,
    content: str,
    agent_name: Optional[str] = None,
) -> list[TaskArtifact]:
    """Persist all v2 artifacts for a stage (planning→brief+prd, dev→implementation+code_link)."""
    if not settings.artifact_store_v2:
        return []

    written: list[TaskArtifact] = []

    if stage_id in AUX_STAGE_LABELS and (content or "").strip():
        written.append(await _append_auxiliary_attachment(
            db, task_id, stage_id, AUX_STAGE_LABELS[stage_id], content, agent_name,
        ))
        try:
            from .manifest_sync import trigger_manifest_refresh
            await trigger_manifest_refresh(str(task_id), db=db)
        except Exception:
            pass
        return written

    if not (content or "").strip():
        return []
    if stage_id == "planning":
        brief = _brief_from_planning(task_title or "任务", content)
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "brief", brief, "docs/00-brief.md", agent_name,
        ))
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "prd", content, STAGE_TO_DOC_FILE["planning"], agent_name,
        ))
    elif stage_id == "development":
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "implementation", content,
            STAGE_TO_DOC_FILE["development"], agent_name,
        ))
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "code_link", content,
            "docs/code-snapshot.md", agent_name,
        ))
    else:
        at = STAGE_TO_ARTIFACT.get(stage_id)
        if at:
            written.append(await _write_one_artifact(
                db, task_id, stage_id, at, content,
                STAGE_TO_DOC_FILE.get(stage_id, ""), agent_name,
            ))

    try:
        from .manifest_sync import trigger_manifest_refresh
        await trigger_manifest_refresh(str(task_id), db=db)
    except Exception:
        pass
    return written


async def write_code_artifacts(
    db: AsyncSession,
    task_id: str,
    project_dir: str,
    agent_name: Optional[str] = None,
) -> list[TaskArtifact]:
    """Write source_manifest.json and build.log from project_dir to v2 artifacts."""
    import os

    written: list[TaskArtifact] = []

    manifest_path = os.path.join(project_dir, "source_manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw_manifest = f.read()
        art = await _write_one_artifact(
            db, task_id, "development", "source_manifest", raw_manifest,
            "source_manifest.json", agent_name,
        )
        written.append(art)

    build_log_path = os.path.join(project_dir, "build.log")
    if os.path.isfile(build_log_path):
        with open(build_log_path, "r", encoding="utf-8") as f:
            raw_log = f.read()
        art = await _write_one_artifact(
            db, task_id, "development", "build_log", raw_log,
            "build.log", agent_name,
        )
        written.append(art)

    if written:
        try:
            from .manifest_sync import trigger_manifest_refresh
            await trigger_manifest_refresh(str(task_id), db=db)
        except Exception:
            pass

    return written


async def write_qa_artifacts(
    db: AsyncSession,
    task_id: str,
    project_dir: str,
    qa_result: dict,
) -> list[TaskArtifact]:
    """Write Phase 6 QA artifacts (test_report, build_log, test_log, screenshot) from QaExecutor output."""
    if not settings.artifact_store_v2:
        return []
    written: list[TaskArtifact] = []

    # --- report markdown ---
    report_lines = [
        "# QA 测试报告\n",
        f"生成时间: {datetime.utcnow().isoformat()}Z\n",
    ]

    rc = qa_result.get("resource_check", {})
    if rc:
        report_lines.append("## 资源检查\n")
        report_lines.append(f"- Node: {'✅' if rc.get('node_available') else '❌'}")
        report_lines.append(f"- pnpm: {'✅' if rc.get('pnpm_available') else '❌'}")
        report_lines.append(f"- Playwright: {'✅' if rc.get('playwright_available') else '❌'}")
        report_lines.append(f"- source_manifest: {'✅' if rc.get('has_source_manifest') else '❌'}")

    for step_name in ("install", "build", "test"):
        step_result = qa_result.get(step_name)
        if not step_result:
            continue
        report_lines.append(f"\n## {step_name.title()}\n")
        report_lines.append(f"- 命令: `{step_result.get('command', '')}`")
        report_lines.append(f"- 退出码: {step_result.get('exit_code', 'N/A')}")
        report_lines.append(f"- 耗时: {step_result.get('duration_ms', 0):.0f}ms")
        report_lines.append(f"- 状态: {'✅ 通过' if step_result.get('ok') else '❌ 失败'}")
        stdout_sum = step_result.get("stdout_summary", "")
        if stdout_sum:
            report_lines.append(f"\nstdout:\n```\n{stdout_sum[:2000]}\n```\n")
        stderr_sum = step_result.get("stderr_summary", "")
        if stderr_sum:
            report_lines.append(f"\nstderr:\n```\n{stderr_sum[:2000]}\n```\n")

    browser = qa_result.get("browser", {})
    if browser:
        report_lines.append("\n## 浏览器 Smoke 测试\n")
        report_lines.append(f"- 页面打开: {'✅' if browser.get('page_opened') else '❌'}")
        report_lines.append(f"- HTTP 状态: {browser.get('status_code', 0)}")
        screenshot_path = browser.get("screenshot_path", "")
        if screenshot_path:
            report_lines.append(f"- 截图: `{screenshot_path}`")
        console_errors = browser.get("console_errors", [])
        if console_errors:
            report_lines.append(f"- Console errors: {len(console_errors)} 条")
            for ce in console_errors[:5]:
                report_lines.append(f"  - `{ce[:200]}`")
        page_text = browser.get("page_text_preview", "")
        if page_text:
            report_lines.append(f"\n页面文本预览:\n> {page_text[:500].replace(chr(10), ' ')}\n")
        error = browser.get("error", "")
        if error:
            report_lines.append(f"\n浏览器错误: {error}\n")

    ok = qa_result.get("ok", False)
    report_lines.append(f"\n## 总体结论\n")
    report_lines.append(f"- 整体: {'✅ 通过' if ok else '❌ 失败'}")

    report_content = "\n".join(report_lines)
    written.append(await _write_one_artifact(
        db, task_id, "testing", "test_report", report_content,
        "docs/05-test-report.md", "Agent-qa",
        metadata_json=qa_result if len(json.dumps(qa_result, default=str)) < 50000 else {"truncated": True},
    ))

    # --- build.log ---
    build_log_path = os.path.join(project_dir, "build.log")
    if os.path.isfile(build_log_path):
        with open(build_log_path, "r", encoding="utf-8") as f:
            raw_log = f.read()
        written.append(await _write_one_artifact(
            db, task_id, "testing", "build_log", raw_log,
            "build.log", "Agent-qa",
        ))

    # --- test.log ---
    test_log_path = os.path.join(project_dir, "test.log")
    if os.path.isfile(test_log_path):
        with open(test_log_path, "r", encoding="utf-8") as f:
            raw_log = f.read()
        written.append(await _write_one_artifact(
            db, task_id, "testing", "test_log", raw_log,
            "test.log", "Agent-qa",
        ))

    # --- browser_screenshot.png ---
    ss_path = browser.get("screenshot_path", "") if browser else ""
    if ss_path and os.path.isfile(ss_path):
        with open(ss_path, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode("ascii")
        written.append(await _write_one_artifact(
            db, task_id, "testing", "screenshot", b64,
            "screenshots/browser_screenshot.png", "Agent-qa",
            metadata_json={"mime": "image/png", "original_path": ss_path},
        ))

    # --- console_errors.json ---
    if browser:
        console_errors = browser.get("console_errors", [])
        if console_errors:
            written.append(await _write_one_artifact(
                db, task_id, "testing", "console_errors",
                json.dumps({"console_errors": console_errors}),
                "console_errors.json", "Agent-qa",
            ))

    if written:
        try:
            from .manifest_sync import trigger_manifest_refresh
            await trigger_manifest_refresh(str(task_id), db=db)
        except Exception:
            pass

    return written


async def write_deploy_artifacts(
    db: AsyncSession,
    task_id: str,
    project_dir: str,
    deploy_result: dict,
) -> list[TaskArtifact]:
    """Write Phase 7 deploy artifacts (preview_url, deploy_manifest, screenshot, ops_runbook).

    ``deploy_result`` is the structured dict from LocalPreview.deploy() or Vercel deploy_to_vercel().
    """
    if not settings.artifact_store_v2:
        return []
    written: list[TaskArtifact] = []

    provider = deploy_result.get("provider", "local")
    deploy_url = deploy_result.get("url", "")
    health_status = deploy_result.get("health_status", "unknown")
    deployed_at = deploy_result.get("deployed_at", datetime.utcnow().isoformat())
    screenshot_path = deploy_result.get("screenshot_path", "")

    # --- preview_url artifact (JSON) ---
    preview_payload = {
        "url": deploy_url,
        "provider": provider,
        "environment": deploy_result.get("environment", "preview"),
        "health_status": health_status,
        "screenshot_path": screenshot_path,
        "deployed_at": deployed_at,
    }
    written.append(await _write_one_artifact(
        db, task_id, "deployment", "preview_url",
        json.dumps(preview_payload, ensure_ascii=False, indent=2),
        "deploy/preview_url.json", "Agent-devops",
        metadata_json=preview_payload,
    ))

    # --- deploy_manifest (existing type) ---
    manifest_content = json.dumps({
        "provider": provider,
        "url": deploy_url,
        "health_status": health_status,
        "deployed_at": deployed_at,
        "project_dir": project_dir,
    }, ensure_ascii=False, indent=2)
    written.append(await _write_one_artifact(
        db, task_id, "deployment", "deploy_manifest",
        manifest_content,
        "deploy/manifest.json", "Agent-devops",
    ))

    # --- deployed_screenshot.png (screenshot type) ---
    if screenshot_path and os.path.isfile(screenshot_path):
        with open(screenshot_path, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode("ascii")
        written.append(await _write_one_artifact(
            db, task_id, "deployment", "screenshot",
            b64,
            "screenshots/deployed_screenshot.png", "Agent-devops",
            metadata_json={"mime": "image/png", "original_path": screenshot_path},
        ))

    # --- ops_runbook (Markdown) ---
    runbook = _format_ops_runbook(provider, deploy_url, health_status, deployed_at)
    written.append(await _write_one_artifact(
        db, task_id, "deployment", "ops_runbook",
        runbook,
        "docs/07-ops-runbook.md", "Agent-devops",
    ))

    if written:
        try:
            from .manifest_sync import trigger_manifest_refresh
            await trigger_manifest_refresh(str(task_id), db=db)
        except Exception:
            pass

    return written


def _format_ops_runbook(provider: str, url: str, health: str, deployed_at: str) -> str:
    return f"""# 部署运维手册

## 部署摘要

- **Provider**: {provider}
- **URL**: {url if url else 'N/A'}
- **健康状态**: {health}
- **部署时间**: {deployed_at}

## 访问方式

| 环境 | URL |
|------|-----|
| Preview | {url if url else '不可用'} |

## 回滚方案

1. 本地 preview：重新运行 `pnpm preview`。
2. Vercel：在 Vercel Dashboard 选择之前的 Deployment 点击 "Promote to Production"。
3. 如使用 Docker：重新部署上一个镜像 Tag。

## 健康检查

- URL 返回 HTTP 200
- 页面内容非空
- Playwright 截图已保存
"""
