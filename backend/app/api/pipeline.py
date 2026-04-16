"""Pipeline API: task management, stage progression, collaboration."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
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

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    source: str = "web"


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
    task = PipelineTask(
        title=body.title,
        description=body.description,
        source=body.source,
        created_by=str(user.id) if user else "api",
        org_id=user.org_id if user else None,
        current_stage_id="planning",
    )
    db.add(task)
    await db.flush()

    for stage_data in _default_stages():
        stage = PipelineStage(task_id=task.id, **stage_data)
        if stage_data["stage_id"] == "planning":
            stage.status = "active"
            stage.started_at = datetime.utcnow()
        db.add(stage)

    await db.flush()

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == task.id)
    )
    return {"task": result.scalar_one()}


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

    target_stage = next((s for s in task.stages if s.stage_id == body.target_stage_id), None)
    if not target_stage:
        raise HTTPException(status_code=400, detail="目标阶段不存在")

    for stage in task.stages:
        if stage.stage_id == task.current_stage_id:
            stage.status = "blocked"

    target_stage.status = "active"
    target_stage.started_at = datetime.utcnow()
    task.current_stage_id = body.target_stage_id

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

async def _run_in_background(coro_factory, task_label: str):
    """Run a coroutine in a standalone background task with its own DB session.

    This prevents the execution from being cancelled when the HTTP client
    disconnects (e.g. user navigates to a different page).
    """
    from ..database import async_session as session_factory
    from ..services.sse import emit_event

    try:
        async with session_factory() as db:
            try:
                await coro_factory(db)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.exception(f"[background] {task_label} failed: {exc}")
                await emit_event("pipeline:auto-error", {
                    "error": str(exc),
                    "label": task_label,
                })
    except Exception as outer:
        logger.exception(f"[background] session error in {task_label}: {outer}")


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

    async def _run(bg_db: AsyncSession):
        from ..services.lead_agent import run_smart_pipeline
        await run_smart_pipeline(bg_db, tid, title, desc)

    asyncio.create_task(_run_in_background(_run, f"smart-run:{tid[:8]}"))
    return {"ok": True, "started": True, "taskId": tid}


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
    previous_outputs = {}
    sorted_stages = sorted(task.stages, key=lambda s: s.sort_order)
    for stage in sorted_stages:
        if stage.output:
            previous_outputs[stage.stage_id] = stage.output

    tid = str(task.id)
    t_title, t_desc = task.title, task.description

    async def _run(bg_db: AsyncSession):
        from ..services.pipeline_engine import execute_stage
        from ..models.pipeline import PipelineTask as PT, PipelineStage as PS
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        result = await execute_stage(
            bg_db,
            task_id=tid,
            task_title=t_title,
            task_description=t_desc,
            stage_id=stage_id,
            previous_outputs=previous_outputs,
        )

        if result.get("ok"):
            db_result = await bg_db.execute(
                select(PT).options(selectinload(PT.stages)).where(PT.id == uuid.UUID(tid))
            )
            db_task = db_result.scalar_one_or_none()
            if db_task:
                ss = sorted(db_task.stages, key=lambda s: s.sort_order)
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

    asyncio.create_task(_run_in_background(_run, f"run-stage:{tid[:8]}/{stage_id}"))
    return {"ok": True, "started": True, "taskId": tid, "stageId": stage_id}


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

    async def _run(bg_db: AsyncSession):
        from ..services.pipeline_engine import execute_full_pipeline
        await execute_full_pipeline(
            bg_db,
            task_id=tid,
            task_title=title,
            task_description=desc,
            force_continue=True,
        )

    asyncio.create_task(_run_in_background(_run, f"auto-run:{tid[:8]}"))
    return {"ok": True, "started": True, "taskId": tid}


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


@router.post("/tasks/{task_id}/dag-run")
async def dag_run(
    task_id: str,
    body: DAGRunRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute pipeline using DAG-based scheduling (parallel stages)."""
    task = await _get_task_or_404(db, task_id, user, load_relations=False)

    from ..services.dag_orchestrator import execute_dag_pipeline
    dag_result = await execute_dag_pipeline(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
        template=body.template,
        complexity=body.complexity,
    )
    await db.commit()
    return {"ok": dag_result.get("ok", False), "taskId": str(task.id), **dag_result}


@router.get("/templates")
async def list_dag_templates():
    """List available DAG pipeline templates."""
    from ..services.dag_orchestrator import PIPELINE_TEMPLATES
    templates = {}
    for name, stages in PIPELINE_TEMPLATES.items():
        templates[name] = {
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

    task = PipelineTask(
        title=body.title,
        description=body.description,
        source="api-e2e",
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
    )

    return {
        "ok": result.get("ok", False),
        "taskId": str(task.id),
        "url": result.get("url", ""),
        "phases": result.get("phases", {}),
    }
