"""
DAG Orchestrator — dependency-based pipeline execution.

Replaces the fixed linear pipeline with a DAG (Directed Acyclic Graph)
where stages can:
- Run in parallel when they share no dependencies
- Be skipped for simple tasks
- Support dynamic stage insertion
- Allow conditional branching (e.g. REJECTED → go back)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models.pipeline import PipelineTask, PipelineStage, PipelineArtifact
from .pipeline_engine import execute_stage
from .sse import emit_event
from .observability import start_trace, complete_trace

logger = logging.getLogger(__name__)


class StageStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class DAGStage:
    """A single stage in the execution DAG."""

    def __init__(
        self,
        stage_id: str,
        label: str,
        role: str,
        depends_on: Optional[List[str]] = None,
        skip_condition: Optional[str] = None,
    ):
        self.stage_id = stage_id
        self.label = label
        self.role = role
        self.depends_on = depends_on or []
        self.skip_condition = skip_condition
        self.status = StageStatus.PENDING
        self.output: Optional[str] = None
        self.error: Optional[str] = None


PIPELINE_TEMPLATES: Dict[str, List[DAGStage]] = {
    "full": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "开发实现", "developer", depends_on=["architecture"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "审查验收", "orchestrator", depends_on=["testing"]),
        DAGStage("deployment", "部署上线", "devops", depends_on=["reviewing"]),
    ],
    "parallel_design": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("architecture", "架构设计", "architect", depends_on=["planning"]),
        DAGStage("development", "开发实现", "developer", depends_on=["planning", "architecture"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
        DAGStage("reviewing", "审查验收", "orchestrator", depends_on=["testing"]),
    ],
    "simple": [
        DAGStage("planning", "需求规划", "product-manager"),
        DAGStage("development", "开发实现", "developer", depends_on=["planning"]),
        DAGStage("testing", "测试验证", "qa-lead", depends_on=["development"]),
    ],
    "review_only": [
        DAGStage("testing", "测试验证", "qa-lead"),
        DAGStage("reviewing", "审查验收", "orchestrator", depends_on=["testing"]),
    ],
}


def get_ready_stages(stages: List[DAGStage]) -> List[DAGStage]:
    """Find all stages whose dependencies are satisfied and can run now."""
    completed = {s.stage_id for s in stages if s.status in (StageStatus.DONE, StageStatus.SKIPPED)}
    return [
        s for s in stages
        if s.status == StageStatus.PENDING
        and all(dep in completed for dep in s.depends_on)
    ]


def resolve_execution_plan(stages: List[DAGStage]) -> List[List[DAGStage]]:
    """Resolve the full execution order as batches of parallel-safe stages."""
    batches: List[List[DAGStage]] = []
    completed: Set[str] = set()
    remaining = [s for s in stages if s.status == StageStatus.PENDING]

    while remaining:
        batch = [
            s for s in remaining
            if all(dep in completed for dep in s.depends_on)
        ]
        if not batch:
            for s in remaining:
                s.status = StageStatus.BLOCKED
            batches.append(remaining)
            break
        batches.append(batch)
        for s in batch:
            completed.add(s.stage_id)
        remaining = [s for s in remaining if s.stage_id not in completed]

    return batches


async def execute_dag_pipeline(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    template: str = "full",
    complexity: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a pipeline using DAG-based scheduling.
    
    Stages without dependencies run in parallel.
    """
    template_stages = PIPELINE_TEMPLATES.get(template, PIPELINE_TEMPLATES["full"])
    stages = [
        DAGStage(s.stage_id, s.label, s.role, list(s.depends_on))
        for s in template_stages
    ]

    trace = start_trace(task_id, task_title)
    await emit_event("pipeline:dag-start", {
        "taskId": task_id, "title": task_title,
        "template": template, "stageCount": len(stages),
    })

    results: List[Dict[str, Any]] = []
    outputs: Dict[str, str] = {}
    batches = resolve_execution_plan(stages)

    for batch_idx, batch in enumerate(batches):
        await emit_event("pipeline:dag-batch", {
            "taskId": task_id, "batchIndex": batch_idx,
            "stageIds": [s.stage_id for s in batch],
        })

        async def _run_stage(stage: DAGStage) -> Dict[str, Any]:
            stage.status = StageStatus.RUNNING
            await emit_event("stage:processing", {
                "taskId": task_id, "stageId": stage.stage_id,
                "label": stage.label, "role": stage.role,
            })

            stage_result = await execute_stage(
                db,
                task_id=task_id,
                task_title=task_title,
                task_description=task_description,
                stage_id=stage.stage_id,
                previous_outputs=outputs,
                trace=trace,
                complexity=complexity,
            )

            if stage_result.get("ok"):
                stage.status = StageStatus.DONE
                stage.output = stage_result.get("content", "")
                outputs[stage.stage_id] = stage.output
                await emit_event("stage:completed", {
                    "taskId": task_id, "stageId": stage.stage_id,
                })
            else:
                stage.status = StageStatus.FAILED
                stage.error = stage_result.get("error", "Unknown error")
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage.stage_id,
                    "error": stage.error,
                })

            return {"stageId": stage.stage_id, **stage_result}

        if len(batch) == 1:
            result = await _run_stage(batch[0])
            results.append(result)
            if not result.get("ok"):
                break
        else:
            batch_results = await asyncio.gather(
                *[_run_stage(s) for s in batch],
                return_exceptions=True,
            )
            for br in batch_results:
                if isinstance(br, Exception):
                    results.append({"ok": False, "error": str(br)})
                else:
                    results.append(br)

            if any(not r.get("ok") for r in results[-len(batch):] if isinstance(r, dict)):
                break

    all_ok = all(r.get("ok", False) for r in results if isinstance(r, dict))
    complete_trace(trace.trace_id, status="completed" if all_ok else "failed")

    await emit_event("pipeline:dag-completed", {
        "taskId": task_id,
        "stagesCompleted": sum(1 for s in stages if s.status == StageStatus.DONE),
        "stagesTotal": len(stages),
    })

    # Persist stage outputs to DB
    db_result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages), selectinload(PipelineTask.artifacts))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    db_task = db_result.scalar_one_or_none()
    if db_task:
        for stage in stages:
            if stage.output:
                db_stage = next(
                    (s for s in db_task.stages if s.stage_id == stage.stage_id), None
                )
                if db_stage:
                    db_stage.output = stage.output
                    db_stage.status = "done"
                    db_stage.completed_at = datetime.utcnow()

                artifact = PipelineArtifact(
                    task_id=db_task.id,
                    artifact_type="document",
                    name=f"{stage.label} 产出",
                    content=stage.output[:50000],
                    stage_id=stage.stage_id,
                )
                db.add(artifact)

        if all_ok:
            db_task.status = "done"
        await db.flush()

    return {
        "ok": all_ok,
        "results": results,
        "traceId": trace.trace_id,
        "template": template,
        "summary": {
            "stagesCompleted": sum(1 for s in stages if s.status == StageStatus.DONE),
            "stagesTotal": len(stages),
            "parallelBatches": len(batches),
        },
    }
