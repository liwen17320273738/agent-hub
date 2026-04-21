"""Pipeline API: task management, stage progression, collaboration."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.pipeline import PipelineTask, PipelineStage, PipelineArtifact
from ..models.user import User
from ..security import get_current_user, get_pipeline_auth
from ..services.collaboration import PIPELINE_STAGES

logger = logging.getLogger(__name__)


def _parse_task_id(task_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的任务 ID 格式")


def _parse_artifact_id(artifact_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的附件 ID")

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    source: str = "web"
    template: Optional[str] = None
    repo_url: Optional[str] = None
    project_path: Optional[str] = None
    # When set to "jira" or "github", the create endpoint immediately
    # mints an issue in that tracker (using the task's title /
    # description) and writes it to ``external_links``. Soft-fails
    # to a warning if the connector isn't configured — task creation
    # itself never 5xxs because of an integration miss.
    auto_link: Optional[str] = None
    auto_link_project: Optional[str] = None
    auto_link_labels: Optional[List[str]] = None
    # Workflow Builder spec — when present, ``template`` is treated as
    # ``"custom"`` and these stages take precedence over any named
    # template. Each entry mirrors ``BackendStage`` from the frontend
    # builder (stage_id / label / role / depends_on / max_retries /
    # on_failure / human_gate / skip_condition).
    custom_stages: Optional[List[Dict[str, object]]] = None


class AdvanceRequest(BaseModel):
    output: str = ""


class RejectRequest(BaseModel):
    target_stage_id: str
    reason: str = ""


class ArtifactRequest(BaseModel):
    artifact_type: str
    name: str
    content: str
    stage_id: str = ""


def _default_stages() -> List[Dict[str, object]]:
    return [
        {"stage_id": s["id"], "label": s["label"], "owner_role": s["role"], "sort_order": i}
        for i, s in enumerate(PIPELINE_STAGES)
    ]


def _reset_stage_for_reject(stage: PipelineStage) -> None:
    """Clear per-stage progress / review / gate fields when rewinding the pipeline."""
    stage.output = None
    stage.completed_at = None
    stage.review_status = None
    stage.reviewer_feedback = None
    stage.reviewer_agent = None
    stage.review_attempts = 0
    stage.approval_id = None
    stage.verify_status = None
    stage.verify_checks = None
    stage.quality_score = None
    stage.gate_status = None
    stage.gate_score = None
    stage.gate_details = None
    stage.last_error = None
    stage.retry_count = 0


def _apply_org_filter(stmt, user: Optional[User]):
    """Scope query to user's org.

    API-key callers (user=None) are restricted to tasks with no org
    (i.e. tasks created by gateway/API). They do NOT get cross-org access.
    """
    if user and user.org_id:
        stmt = stmt.where(PipelineTask.org_id == user.org_id)
    elif user is None:
        stmt = stmt.where(PipelineTask.org_id.is_(None))
    return stmt


@router.get("/utils/validate-local-path")
async def validate_local_path(
    path: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """Resolve and verify a directory path on the machine running the backend.

    Browsers cannot expose full filesystem paths from directory pickers; the
    UI uses this endpoint to confirm candidate paths built from folder names.
    """
    raw = (path or "").strip()
    if not raw:
        return {"ok": False, "resolved": None, "detail": "路径为空"}
    expanded = os.path.expanduser(raw)
    try:
        resolved = os.path.realpath(expanded)
    except OSError as e:
        return {"ok": False, "resolved": None, "detail": str(e)}
    if not os.path.isdir(resolved):
        return {"ok": False, "resolved": resolved, "detail": "路径不存在或不是目录"}
    return {"ok": True, "resolved": resolved, "detail": None}


@router.get("/tasks")
async def list_tasks(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = None,
):
    stmt = select(PipelineTask).options(
        selectinload(PipelineTask.stages),
        selectinload(PipelineTask.artifacts),
    ).order_by(PipelineTask.created_at.desc())

    stmt = _apply_org_filter(stmt, user)

    if status:
        stmt = stmt.where(PipelineTask.status == status)

    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return {"tasks": tasks}


async def _get_task_or_404(
    db: AsyncSession, task_id: str, user: Optional[User], *, load_relations: bool = True,
) -> PipelineTask:
    stmt = select(PipelineTask).where(PipelineTask.id == _parse_task_id(task_id))
    if load_relations:
        stmt = stmt.options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
    stmt = _apply_org_filter(stmt, user)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    return {"task": task}


@router.post("/tasks", status_code=201)
async def create_task(
    body: CreateTaskRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Workflow Builder custom DAG: caller supplied an explicit topology.
    # We persist the spec verbatim on the task (so resume / restart can
    # reconstruct ``DAGStage`` objects) AND project the rows into
    # ``pipeline_stages`` for the existing per-stage UI / per-stage APIs.
    persist_custom: Optional[List[Dict[str, object]]] = None
    if body.custom_stages:
        persist_custom = list(body.custom_stages)
        stages_list = []
        for i, s in enumerate(persist_custom):
            sid = str(s.get("stage_id") or s.get("stageId") or "").strip()
            if not sid:
                continue
            stages_list.append({
                "stage_id": sid,
                "label": str(s.get("label") or sid),
                "owner_role": str(s.get("role") or s.get("owner_role") or "developer"),
                "sort_order": i,
                "max_retries": int(s.get("max_retries") or s.get("maxRetries") or 0),
                "on_failure": str(s.get("on_failure") or s.get("onFailure") or "halt"),
                "human_gate": bool(s.get("human_gate") or s.get("humanGate") or False),
            })
        if not stages_list:
            raise HTTPException(status_code=400, detail="custom_stages 内没有有效阶段")
    elif body.template:
        from ..services.dag_orchestrator import PIPELINE_TEMPLATES
        tmpl_stages = PIPELINE_TEMPLATES.get(body.template)
        if tmpl_stages:
            stages_list = [
                {"stage_id": s.stage_id, "label": s.label, "owner_role": s.role, "sort_order": i}
                for i, s in enumerate(tmpl_stages)
            ]
        else:
            stages_list = _default_stages()
    else:
        stages_list = _default_stages()

    first_stage = stages_list[0]["stage_id"] if stages_list else "planning"

    project_path = None
    if body.repo_url:
        from ..services.project_binding import clone_and_bind
        try:
            project_path = await clone_and_bind(body.repo_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif body.project_path:
        from ..services.project_binding import validate_and_bind
        try:
            project_path = validate_and_bind(body.project_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    task = PipelineTask(
        title=body.title,
        description=body.description,
        source=body.source,
        template=("custom" if persist_custom else body.template),
        repo_url=body.repo_url,
        project_path=project_path or body.project_path,
        created_by=str(user.id) if user else "api",
        org_id=user.org_id if user else None,
        current_stage_id=first_stage,
        custom_stages=persist_custom,
    )
    db.add(task)
    await db.flush()

    for stage_data in stages_list:
        stage = PipelineStage(task_id=task.id, **stage_data)
        if stage_data["stage_id"] == first_stage:
            stage.status = "active"
            stage.started_at = datetime.utcnow()
        db.add(stage)

    await db.flush()

    # ── Optional: auto-create + bind external issue ──────────────────
    # The user opted-in via ``auto_link="jira" | "github"``. We do
    # this *after* flush so the task row exists (and the response
    # includes the link), but *before* the final SELECT so the loaded
    # ``external_links`` already reflects it.
    auto_link_result: Optional[Dict] = None
    if body.auto_link:
        auto_link_result = await _try_auto_link(
            task=task,
            kind=body.auto_link,
            project=body.auto_link_project,
            labels=body.auto_link_labels,
        )
        await db.flush()

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == task.id)
    )
    payload = {"task": result.scalar_one()}
    if auto_link_result is not None:
        payload["autoLink"] = auto_link_result
    return payload


async def _try_auto_link(
    *,
    task: PipelineTask,
    kind: str,
    project: Optional[str],
    labels: Optional[List[str]],
) -> Dict:
    """Best-effort: create an external issue from the task and persist
    it on ``task.external_links``. Returns a status dict for the API
    response — never raises (would otherwise leak an integrations
    failure into the task-creation user flow)."""
    from ..services.connectors import get_connector

    kind_norm = (kind or "").lower()
    if kind_norm not in {"jira", "github"}:
        return {"ok": False, "skipped": True, "reason": f"unsupported kind {kind!r}"}

    conn = get_connector(kind_norm)
    if conn is None:
        logger.warning(
            "[pipeline] auto_link=%s requested but connector not configured; skipping",
            kind_norm,
        )
        return {"ok": False, "skipped": True, "reason": "connector_not_configured"}

    try:
        res = await conn.create_issue(
            title=task.title,
            body=task.description or "",
            labels=labels,
            project=project,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[pipeline] auto_link create_issue raised: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}

    if not res.ok:
        return {
            "ok": False,
            "skipped": res.skipped,
            "error": res.error,
        }

    issue = res.issue
    if issue is None:
        return {"ok": False, "error": "connector returned ok=True with no issue ref"}

    new_link = {
        "kind": issue.kind, "key": issue.key, "url": issue.url,
        "project": issue.project, "id": issue.id,
    }
    existing = list(task.external_links or [])
    existing.append(new_link)
    task.external_links = existing
    return {"ok": True, "link": new_link}


@router.post("/tasks/{task_id}/advance")
async def advance_task(
    task_id: str,
    body: AdvanceRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)

    sorted_stages = sorted(task.stages, key=lambda s: s.sort_order)
    current_idx = next(
        (i for i, s in enumerate(sorted_stages) if s.stage_id == task.current_stage_id), -1
    )

    if current_idx < 0:
        raise HTTPException(status_code=400, detail="当前阶段无效")

    current_stage = sorted_stages[current_idx]
    current_stage.status = "done"
    current_stage.completed_at = datetime.utcnow()
    current_stage.output = body.output or None

    if current_idx + 1 < len(sorted_stages):
        next_stage = sorted_stages[current_idx + 1]
        next_stage.status = "active"
        next_stage.started_at = datetime.utcnow()
        task.current_stage_id = next_stage.stage_id
    else:
        task.status = "done"

    await db.flush()

    result2 = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == _parse_task_id(task_id))
    )
    return {"task": result2.scalar_one()}


@router.post("/tasks/{task_id}/reject")
async def reject_task(
    task_id: str,
    body: RejectRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)

    sorted_stages = sorted(task.stages, key=lambda s: s.sort_order)

    current_idx = next(
        (i for i, s in enumerate(sorted_stages) if s.stage_id == task.current_stage_id),
        -1,
    )
    target_idx = next(
        (i for i, s in enumerate(sorted_stages) if s.stage_id == body.target_stage_id),
        -1,
    )

    if target_idx < 0:
        raise HTTPException(status_code=400, detail="目标阶段不存在")
    if current_idx < 0:
        raise HTTPException(status_code=400, detail="当前阶段无效")
    if target_idx >= current_idx:
        raise HTTPException(status_code=400, detail="只能打回到之前的阶段")

    now = datetime.utcnow()

    for i, stage in enumerate(sorted_stages):
        if i < target_idx:
            continue
        if i == target_idx:
            _reset_stage_for_reject(stage)
            stage.status = "active"
            stage.started_at = now
        else:
            _reset_stage_for_reject(stage)
            stage.status = "pending"
            stage.started_at = None

    task.current_stage_id = body.target_stage_id
    if task.status == "done":
        task.status = "active"

    await db.flush()

    result2 = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == _parse_task_id(task_id))
    )
    return {"task": result2.scalar_one()}


@router.post("/tasks/{task_id}/artifacts")
async def add_artifact(
    task_id: str,
    body: ArtifactRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)

    artifact = PipelineArtifact(
        task_id=task.id,
        artifact_type=body.artifact_type,
        name=body.name,
        content=body.content,
        stage_id=body.stage_id or task.current_stage_id,
    )
    db.add(artifact)
    await db.flush()

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == task.id)
    )
    return {"task": result.scalar_one()}


@router.post("/tasks/{task_id}/attachments/upload")
async def upload_task_attachment(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Upload an image or file; stored as PipelineArtifact (upload_image / upload_file)."""
    task = await _get_task_or_404(db, task_id, user)
    from ..services.pipeline_attachments import save_upload_to_artifact

    await save_upload_to_artifact(db, task, file)
    await db.commit()

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == task.id)
    )
    return {"task": result.scalar_one()}


@router.get("/tasks/{task_id}/attachments/{artifact_id}/file")
async def download_task_attachment(
    task_id: str,
    artifact_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    aid = _parse_artifact_id(artifact_id)
    r = await db.execute(
        select(PipelineArtifact).where(
            PipelineArtifact.id == aid,
            PipelineArtifact.task_id == task.id,
        )
    )
    art = r.scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=404, detail="附件不存在")
    meta = art.metadata_extra or {}
    path = meta.get("storage_path")
    if not path:
        raise HTTPException(status_code=404, detail="无文件内容")
    from ..services.pipeline_attachments import resolve_storage_path_or_404

    fp = resolve_storage_path_or_404(path)
    mime = meta.get("mime") or "application/octet-stream"
    name = meta.get("original_filename") or art.name
    return FileResponse(fp, media_type=mime, filename=name)


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: UpdateTaskRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    updates = body.model_dump(exclude_unset=True)
    for field in ("title", "description", "status"):
        if field in updates:
            setattr(task, field, updates[field])
    await db.flush()
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == _parse_task_id(task_id))
    )
    return {"task": result.scalar_one()}


class StageOutputRequest(BaseModel):
    stageId: Optional[str] = None
    output: str = ""


@router.post("/tasks/{task_id}/stage-output")
async def set_stage_output(
    task_id: str,
    body: StageOutputRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)

    stage_id = body.stageId or task.current_stage_id
    output = body.output
    for stage in task.stages:
        if stage.stage_id == stage_id:
            stage.output = output
            break
    await db.flush()
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    await db.delete(task)
    return {"ok": True}


# --- Background execution helpers ---
#
# All pipeline-class background work (smart-run, auto-run, run-stage,
# DAG runs) goes through the global TaskScheduler so we have a single,
# bounded concurrency point for the whole process. See
# services/task_scheduler.py for rationale.
#
# Each `kind` registered below is restart-safe: if the process dies with
# items waiting in the scheduler queue, they will be re-submitted on next
# boot from Redis. Kinds whose params contain large blobs (prior_outputs,
# previous_outputs) are still persisted, but those blobs are reconstructed
# from the DB on resume rather than carried in the params dict.

from ..services.task_scheduler import get_scheduler, register_kind


def _build_smart_run(params):
    async def _run(bg_db: AsyncSession):
        from ..services.lead_agent import run_smart_pipeline
        await run_smart_pipeline(
            bg_db, params["task_id"], params["task_title"], params["task_description"],
        )
    return _run


def _build_dag_run(params):
    async def _run(bg_db: AsyncSession):
        from ..services.dag_orchestrator import execute_dag_pipeline
        await execute_dag_pipeline(
            bg_db,
            task_id=params["task_id"],
            task_title=params["task_title"],
            task_description=params["task_description"],
            template=params.get("template", "full"),
            complexity=params.get("complexity"),
            project_path=params.get("project_path"),
            resume=bool(params.get("resume", False)),
            custom_stages=params.get("custom_stages"),
        )
    return _run


def _build_auto_run(params):
    async def _run(bg_db: AsyncSession):
        from ..services.pipeline_engine import execute_full_pipeline
        await execute_full_pipeline(
            bg_db,
            task_id=params["task_id"],
            task_title=params["task_title"],
            task_description=params["task_description"],
            force_continue=bool(params.get("force_continue", True)),
            project_path=params.get("project_path"),
        )
    return _run


def _build_run_stage(params):
    async def _run(bg_db: AsyncSession):
        from ..services.pipeline_engine import execute_stage
        from ..models.pipeline import PipelineTask as PT, PipelineStage as PS
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # Reconstruct previous_outputs from DB so we don't carry big
        # blobs through Redis params.
        tid = params["task_id"]
        stage_id = params["stage_id"]
        prev: Dict[str, Any] = {}
        db_result = await bg_db.execute(
            select(PT).options(selectinload(PT.stages)).where(PT.id == uuid.UUID(tid))
        )
        db_task = db_result.scalar_one_or_none()
        if db_task:
            for s in sorted(db_task.stages, key=lambda x: x.sort_order):
                if s.output:
                    prev[s.stage_id] = s.output

        result = await execute_stage(
            bg_db,
            task_id=tid,
            task_title=params["task_title"],
            task_description=params["task_description"],
            stage_id=stage_id,
            previous_outputs=prev,
            project_path=params.get("project_path"),
        )

        if result.get("ok") and db_task:
            ss = sorted(db_task.stages, key=lambda x: x.sort_order)
            cur = next((s for s in ss if s.stage_id == stage_id), None)
            if cur:
                cur.output = result.get("content", "")
                cur.status = "done"
                cur.completed_at = datetime.utcnow()
            cur_idx = next((i for i, s in enumerate(ss) if s.stage_id == stage_id), -1)
            if cur_idx >= 0 and cur_idx + 1 < len(ss):
                nxt = ss[cur_idx + 1]
                nxt.status = "active"
                nxt.started_at = datetime.utcnow()
                db_task.current_stage_id = nxt.stage_id
            elif cur_idx >= 0:
                db_task.status = "done"
                db_task.current_stage_id = "done"
    return _run


def _build_resume_pipeline(params):
    """For the linear /resume endpoint. Reconstructs prior_outputs from
    DB so we don't carry large blobs through Redis."""
    async def _run(bg_db: AsyncSession):
        from ..services.pipeline_engine import execute_full_pipeline
        from ..models.pipeline import PipelineTask as PT, PipelineStage as PS
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        tid = params["task_id"]
        remaining = params["remaining_stages"]

        db_result = await bg_db.execute(
            select(PT).options(selectinload(PT.stages)).where(PT.id == uuid.UUID(tid))
        )
        db_task = db_result.scalar_one_or_none()
        prior: Dict[str, str] = {}
        if db_task:
            for s in db_task.stages:
                if s.status == "done" and s.output and s.stage_id not in remaining:
                    prior[s.stage_id] = s.output

        await execute_full_pipeline(
            bg_db,
            task_id=tid,
            task_title=params["task_title"],
            task_description=params["task_description"],
            stages=remaining,
            force_continue=bool(params.get("force_continue", True)),
            prior_outputs=prior,
            project_path=params.get("project_path"),
        )
    return _run


register_kind("smart-run", _build_smart_run)
register_kind("dag-run", _build_dag_run)
register_kind("auto-run", _build_auto_run)
register_kind("run-stage", _build_run_stage)
register_kind("resume-pipeline", _build_resume_pipeline)


async def _submit_task(
    task_id: str,
    label: str,
    *,
    kind: str,
    params: Dict[str, Any],
) -> str:
    """Submit a pipeline task to the global scheduler, with restart-safe
    persistence. ``kind`` must be registered in ``task_scheduler``.
    """
    return await get_scheduler().submit(
        task_id=task_id, label=label, kind=kind, params=params,
    )


# --- Lead Agent / Smart Pipeline ---

@router.post("/tasks/{task_id}/smart-run")
async def smart_run(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run the full smart pipeline as a background task (returns immediately)."""
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    tid, title, desc = str(task.id), task.title, task.description

    submission_id = await _submit_task(
        tid, f"smart-run:{tid[:8]}",
        kind="smart-run",
        params={"task_id": tid, "task_title": title, "task_description": desc},
    )
    return {"ok": True, "started": True, "taskId": tid, "submissionId": submission_id}


@router.post("/tasks/{task_id}/analyze")
async def analyze_task(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lead Agent analysis only (without execution)."""
    task = await _get_task_or_404(db, task_id, user, load_relations=False)

    from ..services.lead_agent import analyze_and_decompose
    analysis = await analyze_and_decompose(
        db, str(task.id), task.title, task.description,
    )
    return {"ok": analysis.get("ok", False), "taskId": str(task.id), **analysis}


@router.post("/tasks/{task_id}/run-stage")
async def run_single_stage(
    task_id: str,
    body: dict,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute a single pipeline stage as a background task (returns immediately)."""
    task = await _get_task_or_404(db, task_id, user)

    stage_id = body.get("stageId") or task.current_stage_id
    tid = str(task.id)

    submission_id = await _submit_task(
        tid, f"run-stage:{tid[:8]}/{stage_id}",
        kind="run-stage",
        params={
            "task_id": tid,
            "task_title": task.title,
            "task_description": task.description,
            "stage_id": stage_id,
            "project_path": task.project_path,
        },
    )
    return {"ok": True, "started": True, "taskId": tid, "stageId": stage_id, "submissionId": submission_id}


@router.post("/tasks/{task_id}/auto-run")
async def auto_run_pipeline(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute the full pipeline as a background task (returns immediately).

    Progress is reported via SSE events — the client does NOT need to hold
    the HTTP connection open for the entire duration.
    """
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    tid, title, desc = str(task.id), task.title, task.description

    submission_id = await _submit_task(
        tid, f"auto-run:{tid[:8]}",
        kind="auto-run",
        params={
            "task_id": tid,
            "task_title": title,
            "task_description": desc,
            "force_continue": True,
            "project_path": task.project_path,
        },
    )
    return {"ok": True, "started": True, "taskId": tid, "submissionId": submission_id}


# --- Skills + Middleware ---

@router.get("/skills")
async def list_pipeline_skills(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..models.skill import Skill as SkillModel
    result = await db.execute(select(SkillModel).where(SkillModel.enabled.is_(True)))
    skills = result.scalars().all()
    return {"skills": skills}


@router.put("/skills/{skill_name}")
async def toggle_pipeline_skill(
    skill_name: str,
    body: dict,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not user:
        raise HTTPException(status_code=403, detail="API Key 无法修改技能，需要用户登录")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改技能状态")
    from ..models.skill import Skill as SkillModel
    skill = await db.get(SkillModel, skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    skill.enabled = body.get("enabled", True)
    await db.flush()
    return {"ok": True}


@router.get("/middleware/stats")
async def middleware_stats(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.observability import get_recent_traces
    traces = await get_recent_traces(limit=50)
    return {
        "totalTraces": len(traces),
        "traces": [
            {"traceId": t["trace_id"], "status": t["status"], "spanCount": t["span_count"]}
            for t in traces
        ],
    }


@router.get("/stages")
async def list_stages():
    return {"stages": PIPELINE_STAGES}


@router.get("/agent-team")
async def get_agent_team():
    """Return the 5 core expert agents and their stage mappings."""
    from ..services.collaboration import get_team_roster, STAGE_AGENTS
    return {
        "agents": get_team_roster(),
        "stageMapping": STAGE_AGENTS,
    }


# --- DAG Pipeline ---

class DAGRunRequest(BaseModel):
    template: str = "full"
    complexity: Optional[str] = None
    # Optional inline override of the DAG topology — only honoured if
    # the task itself doesn't already carry a ``custom_stages`` spec
    # (which always wins, to keep "what you saved" == "what runs").
    custom_stages: Optional[List[Dict[str, object]]] = None


@router.post("/tasks/{task_id}/dag-run")
async def dag_run(
    task_id: str,
    body: DAGRunRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Submit a DAG pipeline run to the global scheduler (returns immediately).

    Progress streams over SSE — callers should NOT keep this HTTP
    connection open for the duration. Use ``synchronous=true`` only for
    test/CLI use cases that genuinely need the inline reply.
    """
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    tid = str(task.id)
    template = body.template
    # If the task was created with a Workflow Builder spec, that always
    # wins — the body.template field is only meaningful for tasks built
    # off named templates. We forward the verbatim spec into the
    # scheduler params so the worker can rehydrate ``DAGStage`` even if
    # the orchestrator restarts mid-run.
    custom_stages = task.custom_stages if task.custom_stages else body.custom_stages
    if custom_stages:
        template = "custom"

    submission_id = await _submit_task(
        tid, f"dag-run:{tid[:8]}/{template}",
        kind="dag-run",
        params={
            "task_id": tid,
            "task_title": task.title,
            "task_description": task.description,
            "template": template,
            "complexity": body.complexity,
            "project_path": task.project_path,
            "custom_stages": custom_stages,
        },
    )
    return {
        "ok": True, "started": True, "taskId": tid,
        "submissionId": submission_id, "template": template,
    }


@router.post("/tasks/{task_id}/resume-dag")
async def resume_task_dag(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Resume a paused/failed/awaiting-approval DAG pipeline from its last checkpoint.

    This is the DAG-side counterpart to the linear ``/resume`` endpoint
    (see ``resume_pipeline`` below). It hands off to
    ``execute_dag_pipeline(resume=True)``, which restores DONE stages
    from the checkpoint artifact and picks up at the first non-DONE
    stage — including stages that were paused by a human gate.
    """
    task = await _get_task_or_404(db, task_id, user, load_relations=True)

    # If a stage is sitting in `awaiting_approval` from a human gate, the
    # caller is implicitly approving it by resuming. Flip it to `done` so
    # the checkpoint loader treats it as completed and the next stage runs.
    # An explicit `/approve` call from the UI would already have done this,
    # but resuming should be idempotent either way.
    for s in task.stages:
        if s.status == "awaiting_approval":
            s.status = "done"
            s.completed_at = datetime.utcnow()
    if task.stages:
        await db.flush()

    from ..services.pipeline_checkpoint import load_checkpoint
    ckpt = await load_checkpoint(db, str(task.id))
    template = (ckpt.get("template") if ckpt else None) or task.template or "full"

    tid = str(task.id)

    submission_id = await _submit_task(
        tid, f"resume-dag:{tid[:8]}/{template}",
        kind="dag-run",
        params={
            "task_id": tid,
            "task_title": task.title,
            "task_description": task.description,
            "template": template,
            "project_path": task.project_path,
            "resume": True,
            "custom_stages": task.custom_stages if task.custom_stages else None,
        },
    )
    await db.commit()
    return {
        "ok": True, "started": True, "taskId": tid,
        "submissionId": submission_id,
        "resumedFromCheckpoint": bool(ckpt),
        "template": template,
    }


@router.get("/tasks/{task_id}/rca")
async def get_task_rca(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    use_llm: bool = True,
):
    """Generate a structured RCA report for the task by aggregating stage
    errors, span errors, audit events, and inter-agent bus messages.
    Falls back to a deterministic summary when ``use_llm=false`` or when
    no LLM key is configured.
    """
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    from ..services.rca_reporter import generate_rca

    report = await generate_rca(db, task_id=str(task.id), use_llm=use_llm)
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("error") or "RCA failed")
    return report


@router.get("/tasks/{task_id}/checkpoint")
async def get_task_checkpoint(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Inspect the last DAG checkpoint (if any) for a task."""
    task = await _get_task_or_404(db, task_id, user, load_relations=False)
    from ..services.pipeline_checkpoint import load_checkpoint
    ckpt = await load_checkpoint(db, str(task.id))
    return {"taskId": str(task.id), "checkpoint": ckpt}


@router.get("/templates")
async def list_dag_templates():
    """List available DAG pipeline templates with descriptions."""
    from ..services.dag_orchestrator import PIPELINE_TEMPLATES, TEMPLATE_DESCRIPTIONS
    templates = {}
    for name, stages in PIPELINE_TEMPLATES.items():
        desc = TEMPLATE_DESCRIPTIONS.get(name, {})
        templates[name] = {
            "label": desc.get("label", name),
            "description": desc.get("description", ""),
            "icon": desc.get("icon", "📋"),
            "stages": [
                {"id": s.stage_id, "label": s.label, "role": s.role, "dependsOn": s.depends_on}
                for s in stages
            ],
            "stageCount": len(stages),
        }
    return {"templates": templates}


# --- Project Templates & Code Generation ---

@router.get("/project-templates")
async def list_project_templates(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """List available project scaffolding templates."""
    from ..services.codegen import list_templates as list_project_tmpl
    return {"templates": list_project_tmpl()}


class CodeGenRequest(BaseModel):
    template_id: Optional[str] = None


@router.post("/tasks/{task_id}/codegen")
async def run_codegen(
    task_id: str,
    body: CodeGenRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate project code from completed pipeline stages."""
    task = await _get_task_or_404(db, task_id, user)

    outputs = {}
    for stage in task.stages:
        if stage.output:
            outputs[stage.stage_id] = stage.output

    if not outputs:
        raise HTTPException(status_code=400, detail="尚无阶段产出，请先运行 pipeline")

    from ..services.codegen import CodeGenAgent
    agent = CodeGenAgent()
    gen_result = await agent.generate_from_pipeline(
        task_id=str(task.id),
        task_title=task.title,
        pipeline_outputs=outputs,
        template_id=body.template_id,
    )

    if gen_result.get("ok") and gen_result.get("files_written"):
        artifact = PipelineArtifact(
            task_id=task.id,
            artifact_type="codegen",
            name=f"代码生成 — {task.title}",
            content=f"项目目录: {gen_result['project_dir']}\n文件: {', '.join(gen_result['files_written'])}",
            stage_id="development",
        )
        db.add(artifact)
        await db.flush()

    return {"ok": gen_result.get("ok", False), "taskId": str(task.id), **gen_result}


# ── E2E: full lifecycle in one call ─────────────────────────────

class E2ERequest(BaseModel):
    title: str
    description: str = ""
    auto_deploy: bool = True
    dag_template: str = "full"
    repo_url: Optional[str] = None
    project_path: Optional[str] = None


@router.post("/e2e")
async def run_end_to_end(
    body: E2ERequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute the ENTIRE lifecycle: pipeline → codegen → build → deploy → preview → notify.

    This is the single API call that turns a requirement into a deployed app.
    """
    from ..services.collaboration import PIPELINE_STAGES

    e2e_project_path = None
    if body.repo_url:
        from ..services.project_binding import clone_and_bind
        try:
            e2e_project_path = await clone_and_bind(body.repo_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif body.project_path:
        from ..services.project_binding import validate_and_bind
        try:
            e2e_project_path = validate_and_bind(body.project_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    task = PipelineTask(
        title=body.title,
        description=body.description,
        source="api-e2e",
        repo_url=body.repo_url,
        project_path=e2e_project_path or body.project_path,
        created_by=str(user.id) if user else "api",
        org_id=user.org_id if user else None,
        current_stage_id="planning",
    )
    db.add(task)
    await db.flush()

    for i, s in enumerate(PIPELINE_STAGES):
        stage = PipelineStage(
            task_id=task.id,
            stage_id=s["id"],
            label=s["label"],
            owner_role=s["role"],
            sort_order=i,
        )
        if s["id"] == "planning":
            from datetime import datetime
            stage.status = "active"
            stage.started_at = datetime.utcnow()
        db.add(stage)
    await db.flush()

    from ..services.e2e_orchestrator import run_full_e2e

    result = await run_full_e2e(
        db,
        task_id=str(task.id),
        task_title=body.title,
        task_description=body.description,
        auto_deploy=body.auto_deploy,
        dag_template=body.dag_template,
        existing_project_dir=e2e_project_path,
    )

    return {
        "ok": result.get("ok", False),
        "taskId": str(task.id),
        "url": result.get("url", ""),
        "phases": result.get("phases", {}),
    }


# ── Human Approval & Review Endpoints ────────────────────────────────────


class ApprovalBody(BaseModel):
    approved: bool
    comment: str = ""


@router.post("/tasks/{task_id}/stages/{stage_id}/approve")
async def approve_stage(
    task_id: str,
    stage_id: str,
    body: ApprovalBody,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Human approval for a paused pipeline stage."""
    from ..services.guardrails import (
        get_pending_approvals,
        resolve_approval,
    )
    from ..services.sse import emit_event

    pending = await get_pending_approvals(task_id=task_id)
    approval = next((a for a in pending if a.stage_id == stage_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail="No pending approval for this stage")

    reviewer_id = str(user.id) if user else "api"
    reviewer_email = user.email if user else "api-key"

    resolved = await resolve_approval(
        approval_id=approval.id,
        approved=body.approved,
        reviewer=reviewer_id,
        comment=body.comment,
    )
    if not resolved:
        raise HTTPException(status_code=500, detail="Failed to resolve approval")

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task:
        if body.approved:
            task.status = "active"
            stage = next((s for s in task.stages if s.stage_id == stage_id), None)
            if stage:
                stage.status = "done"
                stage.completed_at = datetime.utcnow()

            await emit_event("stage:approval-granted", {
                "taskId": task_id,
                "stageId": stage_id,
                "reviewer": reviewer_email,
                "comment": body.comment,
            })
        else:
            stage = next((s for s in task.stages if s.stage_id == stage_id), None)
            if stage:
                stage.status = "rejected"

            await emit_event("stage:approval-denied", {
                "taskId": task_id,
                "stageId": stage_id,
                "reviewer": reviewer_email,
                "comment": body.comment,
            })

        await db.flush()
        await db.commit()

    return {
        "ok": True,
        "approved": body.approved,
        "stage_id": stage_id,
        "comment": body.comment,
    }


@router.get("/tasks/{task_id}/pending-approvals")
async def get_task_pending_approvals(
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Get all pending approvals for a pipeline task."""
    from ..services.guardrails import get_pending_approvals
    pending = await get_pending_approvals(task_id=task_id)
    return [
        {
            "id": a.id,
            "stage_id": a.stage_id,
            "action": a.action,
            "description": a.description,
            "risk_level": a.risk_level.value if hasattr(a.risk_level, "value") else a.risk_level,
            "created_at": a.created_at,
        }
        for a in pending
    ]


@router.get("/tasks/{task_id}/review-config")
async def get_review_config(
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Get the review configuration for all pipeline stages."""
    from ..services.pipeline_engine import STAGE_REVIEW_CONFIG, AGENT_PROFILES
    config = {}
    for stage_id, conf in STAGE_REVIEW_CONFIG.items():
        reviewer_key = conf.get("reviewer_agent")
        reviewer_name = AGENT_PROFILES.get(reviewer_key, {}).get("name", reviewer_key) if reviewer_key else None
        config[stage_id] = {
            "has_peer_review": reviewer_key is not None,
            "reviewer": reviewer_name,
            "human_gate": conf.get("human_gate", False),
        }
    return config


# ── Quality Gate Endpoints ────────────────────────────────────────

@router.get("/tasks/{task_id}/quality-report")
async def get_quality_report(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a comprehensive quality report for all stages of a task."""
    task = await _get_task_or_404(db, task_id, user)

    stages_data = []
    for stage in sorted(task.stages, key=lambda s: s.sort_order):
        stages_data.append({
            "stage_id": stage.stage_id,
            "output": stage.output or "",
            "gate_status": stage.gate_status,
            "gate_score": stage.gate_score,
            "verify_status": stage.verify_status,
            "quality_score": stage.quality_score,
            "review_status": stage.review_status,
        })

    from ..services.quality_gates import generate_quality_report
    report = await generate_quality_report(
        stages_data,
        task_title=task.title,
        template=task.template,
    )
    report["task_id"] = str(task.id)
    report["overall_quality_score"] = task.overall_quality_score
    return report


class GateOverrideBody(BaseModel):
    reason: str = ""


@router.post("/tasks/{task_id}/stages/{stage_id}/gate-override")
async def override_quality_gate(
    task_id: str,
    stage_id: str,
    body: GateOverrideBody,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Human override for a failed quality gate — marks stage as bypassed."""
    if not user:
        raise HTTPException(status_code=403, detail="Gate override requires user auth")

    task = await _get_task_or_404(db, task_id, user)
    target = next((s for s in task.stages if s.stage_id == stage_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Stage not found")

    if target.gate_status not in ("failed", "warning"):
        raise HTTPException(status_code=400, detail=f"Stage gate is '{target.gate_status}', no override needed")

    reviewer_email = user.email if user else "api"
    target.gate_status = "bypassed"
    target.gate_details = {
        **(target.gate_details or {}),
        "override": {
            "by": reviewer_email,
            "reason": body.reason,
        },
    }

    if task.status == "paused":
        task.status = "active"
    if target.status == "blocked":
        target.status = "done"
        target.completed_at = datetime.utcnow()

    sorted_stages = sorted(task.stages, key=lambda s: s.sort_order)
    idx = next((i for i, s in enumerate(sorted_stages) if s.stage_id == stage_id), -1)
    if idx >= 0 and idx + 1 < len(sorted_stages):
        task.current_stage_id = sorted_stages[idx + 1].stage_id
    elif idx >= 0:
        task.current_stage_id = "done"

    await db.flush()

    from ..services.sse import emit_event
    await emit_event("stage:gate-overridden", {
        "taskId": task_id,
        "stageId": stage_id,
        "by": reviewer_email,
        "reason": body.reason,
    })

    return {
        "ok": True,
        "stage_id": stage_id,
        "gate_status": "bypassed",
        "overridden_by": reviewer_email,
    }


@router.get("/sdlc-templates")
async def list_sdlc_templates():
    """List all SDLC templates with their quality gate configurations."""
    from ..services.dag_orchestrator import PIPELINE_TEMPLATES, TEMPLATE_DESCRIPTIONS
    from ..services.quality_gates import DELIVERABLE_REQUIREMENTS, TEMPLATE_GATE_OVERRIDES

    result = {}
    for name, stages in PIPELINE_TEMPLATES.items():
        desc = TEMPLATE_DESCRIPTIONS.get(name, {})
        gate_overrides = TEMPLATE_GATE_OVERRIDES.get(name, {})

        stage_configs = []
        for s in stages:
            base_req = DELIVERABLE_REQUIREMENTS.get(s.stage_id, {})
            overrides = gate_overrides.get(s.stage_id, {})
            merged = {**base_req, **overrides}
            stage_configs.append({
                "id": s.stage_id,
                "label": s.label,
                "role": s.role,
                "dependsOn": s.depends_on,
                "qualityGate": {
                    "passThreshold": merged.get("pass_threshold", 0.7),
                    "failThreshold": merged.get("fail_threshold", 0.4),
                    "minLength": merged.get("min_length", 300),
                    "requiredSections": merged.get("required_sections", []),
                },
            })

        result[name] = {
            "label": desc.get("label", name),
            "description": desc.get("description", ""),
            "icon": desc.get("icon", "📋"),
            "stageCount": len(stages),
            "stages": stage_configs,
            "hasCustomGates": bool(gate_overrides),
        }

    return {"templates": result}


class ResumeBody(BaseModel):
    from_stage: Optional[str] = None
    force_continue: bool = False


@router.post("/tasks/{task_id}/resume")
async def resume_pipeline(
    task_id: str,
    body: ResumeBody,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks = None,
):
    """Resume a paused pipeline from the last completed stage or a specific stage."""
    from ..services.pipeline_engine import STAGE_ROLE_PROMPTS
    from ..services.sse import emit_event

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("paused", "active"):
        raise HTTPException(status_code=400, detail=f"Task status is '{task.status}', cannot resume")

    all_stages = list(STAGE_ROLE_PROMPTS.keys())

    done_outputs: Dict[str, str] = {}
    resume_from_idx = 0

    sorted_stages = sorted(task.stages, key=lambda s: s.sort_order or 0)
    for s in sorted_stages:
        if s.status == "done" and s.output and s.stage_id in all_stages:
            done_outputs[s.stage_id] = s.output
            stage_idx = all_stages.index(s.stage_id)
            resume_from_idx = max(resume_from_idx, stage_idx + 1)

    if body.from_stage and body.from_stage in all_stages:
        resume_from_idx = all_stages.index(body.from_stage)

    remaining_stages = all_stages[resume_from_idx:]
    if not remaining_stages:
        return {"ok": True, "message": "All stages already completed"}

    task.status = "active"
    for s in sorted_stages:
        if s.stage_id in remaining_stages and s.status in ("rejected", "awaiting_approval", "paused"):
            s.status = "pending"
    await db.flush()
    await db.commit()

    await emit_event("pipeline:resumed", {
        "taskId": task_id,
        "fromStage": remaining_stages[0],
        "stages": remaining_stages,
    })

    submission_id = await _submit_task(
        task_id, f"resume:{task_id[:8]}",
        kind="resume-pipeline",
        params={
            "task_id": task_id,
            "task_title": task.title,
            "task_description": task.description or "",
            "remaining_stages": remaining_stages,
            "force_continue": body.force_continue,
            "project_path": task.project_path,
        },
    )

    return {
        "ok": True,
        "resumed_from": remaining_stages[0],
        "remaining_stages": remaining_stages,
        "prior_outputs": list(done_outputs.keys()),
        "submissionId": submission_id,
    }


# ---------- Cost Governor endpoints ----------

class BudgetSetBody(BaseModel):
    budget_usd: float
    soft_ratio: float = 0.6
    hard_ratio: float = 1.0


class BudgetRaiseBody(BaseModel):
    additional_usd: float


@router.get("/tasks/{task_id}/budget")
async def get_budget(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the live spend snapshot for a task."""
    await _get_task_or_404(db, task_id, user)
    from ..services.cost_governor import get_task_budget
    return await get_task_budget(task_id)


@router.post("/tasks/{task_id}/budget")
async def set_budget(
    task_id: str,
    body: BudgetSetBody,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Override the per-task budget (USD) before/while it runs."""
    await _get_task_or_404(db, task_id, user)
    from ..services.cost_governor import set_task_budget, get_task_budget
    if body.budget_usd <= 0:
        raise HTTPException(status_code=400, detail="budget_usd must be > 0")
    if not (0 < body.soft_ratio <= body.hard_ratio):
        raise HTTPException(status_code=400, detail="soft_ratio must be > 0 and <= hard_ratio")
    await set_task_budget(
        task_id, body.budget_usd,
        soft_ratio=body.soft_ratio, hard_ratio=body.hard_ratio,
    )
    return await get_task_budget(task_id)


@router.post("/tasks/{task_id}/budget/raise")
async def raise_budget_endpoint(
    task_id: str,
    body: BudgetRaiseBody,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Approve more budget after the governor blocked the task."""
    await _get_task_or_404(db, task_id, user)
    from ..services.cost_governor import raise_budget, get_task_budget
    if body.additional_usd <= 0:
        raise HTTPException(status_code=400, detail="additional_usd must be > 0")
    new_budget = await raise_budget(task_id, body.additional_usd)
    snapshot = await get_task_budget(task_id)
    snapshot["new_budget_usd"] = new_budget
    return snapshot
