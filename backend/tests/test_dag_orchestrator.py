"""Tests for DAG orchestrator logic."""
from __future__ import annotations

from app.services.dag_orchestrator import (
    DAGStage,
    StageStatus,
    get_ready_stages,
    resolve_execution_plan,
    _should_skip,
    _extract_rejection_target,
    _reset_to_stage,
    PIPELINE_TEMPLATES,
)


def test_get_ready_stages_initial():
    """First stage with no dependencies should be ready."""
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage("dev", "Dev", "dev", depends_on=["planning"]),
    ]
    ready = get_ready_stages(stages)
    assert len(ready) == 1
    assert ready[0].stage_id == "planning"


def test_get_ready_stages_after_completion():
    """Stages should become ready when dependencies complete."""
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage("dev", "Dev", "dev", depends_on=["planning"]),
    ]
    stages[0].status = StageStatus.DONE
    ready = get_ready_stages(stages)
    assert len(ready) == 1
    assert ready[0].stage_id == "dev"


def test_parallel_stages():
    """Multiple stages with same dependencies can run in parallel."""
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage("arch", "Arch", "arch", depends_on=["planning"]),
        DAGStage("design", "Design", "designer", depends_on=["planning"]),
    ]
    stages[0].status = StageStatus.DONE
    ready = get_ready_stages(stages)
    assert len(ready) == 2


def test_resolve_execution_plan():
    """Execution plan should produce correct batches."""
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage("arch", "Arch", "arch", depends_on=["planning"]),
        DAGStage("dev", "Dev", "dev", depends_on=["arch"]),
    ]
    batches = resolve_execution_plan(stages)
    assert len(batches) == 3
    assert batches[0][0].stage_id == "planning"
    assert batches[1][0].stage_id == "arch"
    assert batches[2][0].stage_id == "dev"


def test_should_skip_simple_task():
    outputs = {"planning": "Short plan."}
    assert _should_skip("simple_task", outputs) is True
    outputs = {"planning": "A" * 600}
    assert _should_skip("simple_task", outputs) is False


def test_should_skip_approved():
    assert _should_skip("approved", {"reviewing": "Result: APPROVED"}) is True
    assert _should_skip("approved", {"reviewing": "Result: REJECTED"}) is False


def test_skip_condition_in_ready_stages():
    """Stages with met skip conditions should be marked SKIPPED."""
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage(
            "arch", "Arch", "arch",
            depends_on=["planning"], skip_condition="simple_task",
        ),
    ]
    stages[0].status = StageStatus.DONE
    outputs = {"planning": "Short"}
    ready = get_ready_stages(stages, outputs)
    assert len(ready) == 0
    assert stages[1].status == StageStatus.SKIPPED


def test_extract_rejection_target():
    content = "评审不通过，请返回 architecture 阶段重新设计"
    assert _extract_rejection_target(content) == "architecture"


def test_extract_rejection_target_default():
    assert _extract_rejection_target("REJECTED") == "planning"


def test_reset_to_stage():
    stages = [
        DAGStage("planning", "Plan", "pm"),
        DAGStage("arch", "Arch", "arch", depends_on=["planning"]),
        DAGStage("dev", "Dev", "dev", depends_on=["arch"]),
        DAGStage("reviewing", "Review", "reviewer", depends_on=["dev"]),
    ]
    for s in stages:
        s.status = StageStatus.DONE

    _reset_to_stage(stages, "arch")
    assert stages[0].status == StageStatus.DONE
    assert stages[1].status == StageStatus.PENDING
    assert stages[2].status == StageStatus.PENDING
    assert stages[3].status == StageStatus.DONE  # reviewing excluded from reset


def test_all_templates_valid():
    """All templates should have valid stage structures."""
    for name, stages in PIPELINE_TEMPLATES.items():
        assert len(stages) > 0, f"Template {name} is empty"
        stage_ids = {s.stage_id for s in stages}
        for s in stages:
            for dep in s.depends_on:
                assert dep in stage_ids, (
                    f"Template {name}: {s.stage_id} depends on unknown {dep}"
                )


def test_adaptive_template_exists():
    assert "adaptive" in PIPELINE_TEMPLATES
