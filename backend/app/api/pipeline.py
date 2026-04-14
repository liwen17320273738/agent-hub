"""Pipeline API: task management, stage progression, collaboration."""
from __future__ import annotations

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


@router.get("/health")
async def pipeline_health():
    return {"pipeline": "online", "stages": len(PIPELINE_STAGES)}


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

    if status:
        stmt = stmt.where(PipelineTask.status == status)

    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
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
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    return {"task": result2.scalar_one()}


@router.post("/tasks/{task_id}/reject")
async def reject_task(
    task_id: str,
    body: RejectRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    return {"task": result2.scalar_one()}


@router.post("/tasks/{task_id}/artifacts")
async def add_artifact(
    task_id: str,
    body: ArtifactRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await db.get(PipelineTask, uuid.UUID(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: dict,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await db.get(PipelineTask, uuid.UUID(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    for field in ("title", "description", "status"):
        if field in body:
            setattr(task, field, body[field])
    await db.flush()
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    return {"task": result.scalar_one()}


@router.post("/tasks/{task_id}/stage-output")
async def set_stage_output(
    task_id: str,
    body: dict,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    stage_id = body.get("stageId", task.current_stage_id)
    output = body.get("output", "")
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
    task = await db.get(PipelineTask, uuid.UUID(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await db.delete(task)
    return {"ok": True}


# --- Lead Agent / Smart Pipeline ---

@router.post("/tasks/{task_id}/smart-run")
async def smart_run(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run the full smart pipeline (Lead Agent decomposition + parallel execution)."""
    result = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    from ..services.lead_agent import run_smart_pipeline
    pipeline_result = await run_smart_pipeline(
        db, str(task.id), task.title, task.description,
    )
    await db.commit()
    return {"ok": pipeline_result.get("ok", False), "taskId": str(task.id), **pipeline_result}


@router.post("/tasks/{task_id}/analyze")
async def analyze_task(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lead Agent analysis only (without execution)."""
    result = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
    """Execute a single pipeline stage using the enhanced pipeline engine."""
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    stage_id = body.get("stageId") or task.current_stage_id
    previous_outputs = {}
    for stage in sorted(task.stages, key=lambda s: s.sort_order):
        if stage.output:
            previous_outputs[stage.stage_id] = stage.output

    from ..services.pipeline_engine import execute_stage
    stage_result = await execute_stage(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
        stage_id=stage_id,
        previous_outputs=previous_outputs,
    )
    await db.commit()
    return {"ok": stage_result.get("ok", False), "taskId": str(task.id), "stageId": stage_id, **stage_result}


@router.post("/tasks/{task_id}/auto-run")
async def auto_run_pipeline(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute the full pipeline sequentially using the enhanced engine."""
    result = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    from ..services.pipeline_engine import execute_full_pipeline
    pipeline_result = await execute_full_pipeline(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
    )
    await db.commit()
    return {"ok": pipeline_result.get("ok", False), "taskId": str(task.id), **pipeline_result}


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
    traces = get_recent_traces(limit=50)
    return {
        "totalTraces": len(traces),
        "traces": [
            {"traceId": t.trace_id, "status": t.status, "spanCount": len(t.spans)}
            for t in traces
        ],
    }


@router.get("/stages")
async def list_stages():
    return {"stages": PIPELINE_STAGES}


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
    result = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
        created_by="e2e",
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
