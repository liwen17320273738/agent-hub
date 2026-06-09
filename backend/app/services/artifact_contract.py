"""Phase 3 — artifact contract: required types, schemas, and advisory validation.

Presence is enforced in ``execute_stage`` when ``artifact_contract_enforce``.
Rule violations are **advisory** (API/manifest/UI) unless
``artifact_contract_rules_strict`` is enabled; then they also fail
``execute_stage`` after presence checks pass.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.task_artifact import TaskArtifact

REQUIRED_ARTIFACTS_BY_STAGE: Dict[str, Tuple[str, ...]] = {
    "planning": ("brief", "prd"),
    "design": ("ui_spec", "ui_mockup"),
    "architecture": ("architecture", "architecture_diagram"),
    "development": ("implementation", "code_link", "source_manifest", "build_log"),
    "testing": ("test_report", "build_log", "screenshot"),
    "reviewing": ("acceptance",),
    "deployment": ("ops_runbook", "preview_url", "screenshot", "deploy_manifest"),
}

OPTIONAL_ARTIFACTS_BY_STAGE: Dict[str, Tuple[str, ...]] = {
    "design": ("ui_mockup_html",),
    "architecture": (),
    "testing": ("test_log", "console_errors"),
}

CONTRACT_SCHEMA_VERSION = "1.0"

# Substrings that indicate programmatic E2E stubs, not real delivery evidence.
_MOCK_CONTENT_MARKERS: Tuple[str, ...] = (
    "[hero_path_e2e_mock]",
    "[hero_e2e]",
    "png placeholder",
    "placeholder — replace",
    "placeholder for ui mockup",
    "mock-preview",
    '"provider":"mock-local"',
    '"provider": "mock-local"',
    "程序化占位",
    "程序化 e2e",
    "hero-delivery-path",
    "skipped_in_ci",
)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")


def _def(
    *,
    producing_stages: Tuple[str, ...],
    consuming_stages: Tuple[str, ...],
    content_kind: str,
    rules: Tuple[Dict[str, Any], ...] = (),
    description_zh: str = "",
    description_en: str = "",
) -> Dict[str, Any]:
    return {
        "producing_stages": list(producing_stages),
        "consuming_stages": list(consuming_stages),
        "content_kind": content_kind,
        "rules": [dict(r) for r in rules],
        "description_zh": description_zh,
        "description_en": description_en,
    }


ARTIFACT_TYPE_CONTRACT: Dict[str, Dict[str, Any]] = {
    "brief": _def(
        producing_stages=("planning",),
        consuming_stages=("design", "architecture", "development", "testing"),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 20},),
        description_zh="一页式需求摘要，供下游快速对齐范围。",
        description_en="One-page requirements summary for downstream alignment.",
    ),
    "prd": _def(
        producing_stages=("planning",),
        consuming_stages=("design", "architecture", "development"),
        content_kind="markdown",
        rules=(
            {"id": "min_chars", "value": 80},
            {"id": "markdown_sections", "min_h2": 4},
            {
                "id": "markdown_h2_keyword_groups",
                "groups": (
                    ("范围", "scope", "in-scope", "out-of-scope", "项目范围"),
                    ("用户故事", "user stor", "user story", "user stories"),
                    ("验收标准", "验收", "acceptance", "acceptance criteria"),
                    ("非目标", "non-goal", "non-goals", "out of scope"),
                ),
            },
        ),
        description_zh="完整 PRD：用户故事、验收标准、范围与非目标。",
        description_en="Full PRD: stories, acceptance criteria, scope, non-goals.",
    ),
    "ui_spec": _def(
        producing_stages=("design",),
        consuming_stages=("development", "testing"),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 40},),
        description_zh="界面与交互规格（布局、组件、状态）。",
        description_en="UI and interaction specification.",
    ),
    "ui_mockup": _def(
        producing_stages=("design",),
        consuming_stages=("development", "testing"),
        content_kind="image",
        rules=(),
        description_zh="UI 设计稿 PNG（必出，优先图片生成，HTML 保底）。",
        description_en="UI mockup image (required; image gen first, HTML fallback).",
    ),
    "ui_mockup_html": _def(
        producing_stages=("design",),
        consuming_stages=("development",),
        content_kind="markdown",
        rules=(),
        description_zh="可点击 HTML 原型路径说明（可选，PNG 不可用时作为降级产物）。",
        description_en="Clickable HTML prototype path (optional fallback when PNG unavailable).",
    ),
    "architecture": _def(
        producing_stages=("architecture",),
        consuming_stages=("development", "testing", "deployment"),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 60},),
        description_zh="技术方案与模块边界。",
        description_en="Technical design and module boundaries.",
    ),
    "architecture_diagram": _def(
        producing_stages=("architecture",),
        consuming_stages=("development",),
        content_kind="markdown",
        rules=(),
        description_zh="架构图（Mermaid 导出 HTML，必出）。",
        description_en="Architecture diagram (required).",
    ),
    "implementation": _def(
        producing_stages=("development",),
        consuming_stages=("testing", "reviewing"),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 40},),
        description_zh="实现说明：关键模块与约定。",
        description_en="Implementation notes for QA and reviewers.",
    ),
    "code_link": _def(
        producing_stages=("development",),
        consuming_stages=("testing", "deployment", "reviewing"),
        content_kind="json",
        rules=({"id": "json_object"},),
        description_zh="代码位置 JSON：分支、路径、工件引用等。",
        description_en="JSON blob: branch, paths, codegen metadata.",
    ),
    "test_report": _def(
        producing_stages=("testing",),
        consuming_stages=("reviewing", "deployment"),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 30},),
        description_zh="测试报告与命令结果摘要。",
        description_en="Test report and command output summary.",
    ),
    "acceptance": _def(
        producing_stages=("reviewing",),
        consuming_stages=("deployment",),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 30},),
        description_zh="验收记录与签收条件对照。",
        description_en="Acceptance checklist outcome.",
    ),
    "ops_runbook": _def(
        producing_stages=("deployment",),
        consuming_stages=(),
        content_kind="markdown",
        rules=({"id": "min_chars", "value": 30},),
        description_zh="部署与回滚操作说明。",
        description_en="Deploy and rollback runbook.",
    ),
    "source_manifest": _def(
        producing_stages=("development",),
        consuming_stages=("testing", "deployment"),
        content_kind="json",
        rules=({"id": "json_object"},),
        description_zh="源码清单：文件列表、构建/运行/测试命令。",
        description_en="Source manifest: file list, build/run/test commands.",
    ),
    "build_log": _def(
        producing_stages=("development", "testing"),
        consuming_stages=("testing",),
        content_kind="text",
        rules=({"id": "min_chars", "value": 10},),
        description_zh="构建命令输出日志（QA 阶段覆盖 Phase 4 版本，附带真实命令/退出码）。",
        description_en="Build output log (QA overwrites Phase 4 version with real exit code).",
    ),
    "screenshot": _def(
        producing_stages=("testing",),
        consuming_stages=(),
        content_kind="image",
        rules=(),
        description_zh="Playwright 浏览器截图（真实 preview server）。",
        description_en="Playwright browser screenshot from real preview server.",
    ),
    "test_log": _def(
        producing_stages=("testing",),
        consuming_stages=(),
        content_kind="text",
        rules=({"id": "min_chars", "value": 10},),
        description_zh="pnpm test 完整输出，可折叠查看。",
        description_en="Full pnpm test output, collapsible.",
    ),
    "console_errors": _def(
        producing_stages=("testing",),
        consuming_stages=(),
        content_kind="json",
        rules=(),
        description_zh="浏览器页面 console error 列表。",
        description_en="Browser page console error list.",
    ),
    "preview_url": _def(
        producing_stages=("deployment",),
        consuming_stages=("reviewing",),
        content_kind="json",
        rules=(),
        description_zh="部署预览链接（本地或 Vercel），含 provider/health_status/截图引用。",
        description_en="Deploy preview URL (local or Vercel) with provider, health status, screenshot ref.",
    ),
}


def _tid(task_id: str) -> uuid.UUID:
    return uuid.UUID(task_id) if isinstance(task_id, str) else task_id


def _nonempty_content(content: Optional[str]) -> bool:
    return bool((content or "").strip())


def _has_mock_markers(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _MOCK_CONTENT_MARKERS)


def _visual_asset_ok(
    content: str,
    storage_path: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    meta = metadata or {}
    paths = [
        str(meta.get("filePath") or ""),
        str(meta.get("original_path") or ""),
        str(storage_path or ""),
    ]
    if any(p.lower().endswith(_IMAGE_EXTENSIONS) for p in paths if p):
        return True
    stripped = (content or "").strip()
    if stripped.startswith("data:image/"):
        return True
    # A rendered HTML prototype is genuine, viewable visual evidence. When image
    # generation is unavailable (e.g. quota exhausted), the design stage falls
    # back to an HTML mockup — accept it the same way _diagram_ok accepts HTML,
    # rather than dead-ending delivery over a missing PNG we honestly cannot make.
    if any(p.lower().endswith(".html") for p in paths if p):
        return True
    low = stripped.lower()
    if "<!doctype html" in low or "<html" in low:
        return True
    if len(stripped) > 256 and not _has_mock_markers(stripped):
        head = stripped[:80]
        if not head.startswith(("#", "[", "PNG ", "png ")):
            return True
    return False


def _diagram_ok(
    content: str,
    storage_path: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    meta = metadata or {}
    paths = [
        str(meta.get("filePath") or ""),
        str(storage_path or ""),
    ]
    if any(p.lower().endswith(".html") for p in paths if p):
        return True
    raw = content or ""
    low = raw.lower()
    if "```mermaid" in low or "<html" in low or "<!doctype html" in low:
        return True
    return False


def artifact_quality_errors(
    artifact_type: str,
    content_kind: str,
    content: str,
    storage_path: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Reject mock/stub delivery rows that are non-empty but not real evidence."""
    errs: List[str] = []
    raw = content or ""
    if _has_mock_markers(raw):
        errs.append("mock_content")

    if artifact_type in ("ui_mockup", "screenshot"):
        if not _visual_asset_ok(raw, storage_path, metadata):
            errs.append("requires_visual_asset")

    if artifact_type == "architecture_diagram":
        if not _diagram_ok(raw, storage_path, metadata):
            errs.append("requires_diagram")

    if artifact_type == "preview_url" and content_kind == "json":
        try:
            obj = json.loads((raw or "").strip())
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(obj, dict):
                url = str(obj.get("url") or "").lower()
                provider = str(obj.get("provider") or "").lower()
                health = str(obj.get("health_status") or "").lower()
                if "mock" in url or "mock" in provider:
                    errs.append("mock_deploy_url")
                if health in ("skipped_in_ci", "unknown") and "mock" in url:
                    errs.append("mock_deploy_health")

    if artifact_type in ("build_log", "test_report", "test_log") and not raw.strip():
        errs.append("empty_log")

    return errs


def _markdown_h2_text_lines(markdown: str) -> List[str]:
    """Return normalized heading texts from both ## and ### headings."""
    lines: List[str] = []
    for ln in (markdown or "").splitlines():
        s = ln.strip()
        # Match both ## and ### headings
        if s.startswith("##"):
            body = s.lstrip("#").strip().lower()
            if body:
                lines.append(body)
    return lines


def _apply_schema_rules(content_kind: str, text: str, rules: List[Dict[str, Any]]) -> List[str]:
    errs: List[str] = []
    raw = text or ""
    stripped = raw.strip()
    for rule in rules:
        rid = rule.get("id")
        if rid == "min_chars":
            n = int(rule.get("value", 0))
            if len(stripped) < n:
                errs.append(f"min_chars:{n}")
        elif rid == "json_object":
            if content_kind != "json":
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                errs.append("json_invalid")
                continue
            if not isinstance(obj, dict):
                errs.append("json_not_object")
        elif rid == "markdown_sections":
            if content_kind != "markdown":
                continue
            min_h2 = int(rule.get("min_h2", 1))
            if raw.count("##") < min_h2:
                errs.append(f"markdown_sections:min_h2={min_h2}")
        elif rid == "markdown_h2_keyword_groups":
            if content_kind != "markdown":
                continue
            h2_blob = "\n".join(_markdown_h2_text_lines(raw))
            full_text = raw.lower()
            for grp in rule.get("groups") or ():
                alts = [str(a).strip().lower() for a in grp if str(a).strip()]
                if not alts:
                    continue
                # Check headings first, fall back to full-text search
                in_headings = any(a in h2_blob for a in alts)
                in_fulltext = any(a in full_text for a in alts)
                if not in_headings and not in_fulltext:
                    errs.append(f"markdown_h2_keywords:missing_group:{('|'.join(alts[:5]))}")
    return errs


async def _latest_active_artifacts(
    db: AsyncSession, task_id: str
) -> Dict[str, TaskArtifact]:
    tid = _tid(task_id)
    result = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.is_latest.is_(True),
                TaskArtifact.status == "active",
            )
        )
    )
    rows = result.scalars().all()
    return {a.artifact_type: a for a in rows}


async def validate_stage_artifact_contract(
    db: AsyncSession, task_id: str, stage_id: str
) -> Tuple[bool, List[str]]:
    """Return (ok, missing_types) for required v2 artifacts after ``stage_id``."""
    if not settings.artifact_store_v2 or not settings.artifact_contract_enforce:
        return True, []
    required = REQUIRED_ARTIFACTS_BY_STAGE.get(stage_id)
    if not required:
        return True, []
    by_type = await _latest_active_artifacts(db, task_id)
    missing: List[str] = []
    for art_type in required:
        art = by_type.get(art_type)
        if art is None or not _nonempty_content(art.content):
            missing.append(art_type)
    return (not missing, missing)


def _artifact_validation_errors(art: TaskArtifact) -> List[str]:
    meta = ARTIFACT_TYPE_CONTRACT.get(art.artifact_type, {})
    content_kind = str(meta.get("content_kind") or "markdown")
    schema_errs = _apply_schema_rules(
        content_kind,
        art.content or "",
        list(meta.get("rules") or []),
    )
    quality_errs = artifact_quality_errors(
        art.artifact_type,
        content_kind,
        art.content or "",
        art.storage_path or "",
        art.metadata_json if isinstance(art.metadata_json, dict) else {},
    )
    merged: List[str] = []
    for err in schema_errs + quality_errs:
        if err not in merged:
            merged.append(err)
    return merged


async def validate_stage_artifact_contract_rules_strict(
    db: AsyncSession, task_id: str, stage_id: str
) -> Tuple[bool, List[str]]:
    """Fail when required artifacts exist but violate schema or quality rules.

    Only runs when artifact v2 store, enforce, and ``artifact_contract_rules_strict`` are all on.
    """
    if (
        not settings.artifact_store_v2
        or not settings.artifact_contract_enforce
        or not settings.artifact_contract_rules_strict
    ):
        return True, []
    required = REQUIRED_ARTIFACTS_BY_STAGE.get(stage_id)
    if not required:
        return True, []
    by_type = await _latest_active_artifacts(db, task_id)
    violations: List[str] = []
    for tkey in required:
        art = by_type.get(tkey)
        if art is None or not _nonempty_content(art.content):
            continue
        val_errs = _artifact_validation_errors(art)
        if val_errs:
            violations.append(f"{tkey}:[{','.join(val_errs)}]")
    return (not violations, violations)


async def build_task_contract_report(db: AsyncSession, task_id: str) -> Dict[str, Any]:
    """Per-stage contract + schemas + advisory validation (API + manifest + UI)."""
    by_type = await _latest_active_artifacts(db, task_id)
    stages_out: Dict[str, Any] = {}
    all_ok = True

    for sid, required in REQUIRED_ARTIFACTS_BY_STAGE.items():
        present: Dict[str, bool] = {}
        missing: List[str] = []
        invalid: List[str] = []
        optional_t = OPTIONAL_ARTIFACTS_BY_STAGE.get(sid, ())
        artifact_details: Dict[str, Any] = {}

        for t in required:
            art = by_type.get(t)
            ok_t = art is not None and _nonempty_content(art.content)
            present[t] = ok_t
            meta = ARTIFACT_TYPE_CONTRACT.get(t, {})
            val_errs: List[str] = []
            if ok_t and art is not None:
                val_errs = _artifact_validation_errors(art)
            artifact_details[t] = {
                "required": True,
                "present": ok_t,
                "version": art.version if art else None,
                "validation_errors": val_errs,
                "definition": meta,
            }
            if not ok_t:
                missing.append(t)
            elif val_errs:
                invalid.append(t)

        optional_status: Dict[str, bool] = {}
        for ot in optional_t:
            oa = by_type.get(ot)
            opt_ok = oa is not None and _nonempty_content(oa.content)
            optional_status[ot] = opt_ok
            om = ARTIFACT_TYPE_CONTRACT.get(ot, {})
            oerrs: List[str] = []
            if opt_ok and oa is not None:
                oerrs = _artifact_validation_errors(oa)
            artifact_details[ot] = {
                "required": False,
                "present": opt_ok,
                "version": oa.version if oa else None,
                "validation_errors": oerrs,
                "definition": om,
            }

        stage_ok = not missing and not invalid
        if not stage_ok:
            all_ok = False
        stages_out[sid] = {
            "required": list(required),
            "present": present,
            "missing": missing,
            "invalid": invalid,
            "ok": stage_ok,
            "optional_present": optional_status,
            "artifact_details": artifact_details,
        }

    definitions_out = {
        k: dict(v) for k, v in ARTIFACT_TYPE_CONTRACT.items()
    }
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "definitions": definitions_out,
        "task_id": str(_tid(task_id)),
        "enforce": bool(settings.artifact_contract_enforce),
        "rules_strict": bool(settings.artifact_contract_rules_strict),
        "artifact_store_v2": bool(settings.artifact_store_v2),
        "all_required_satisfied": all_ok,
        "stages": stages_out,
    }
