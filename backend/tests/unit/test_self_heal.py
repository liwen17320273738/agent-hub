"""Unit tests for single-task self-healing.

When the acceptance reviewer emits ``REJECTED`` + ``REJECT_TO: <stage>``,
the orchestrator should:

  1. Reset the target stage (and downstream) to PENDING.
  2. Extract the *reason* from the reviewer's free-form text.
  3. Stamp the reason onto the target stage as ``reject_feedback``.
  4. Increment ``reject_count`` so we can see how many times this
     stage has been bounced back in this task run.

When the orchestrator then re-runs the target stage, ``execute_stage``
must inject the feedback into the system prompt as a "self-heal"
patch — so the agent sees its previous criticism instead of running
the exact same prompt blind.
"""
from __future__ import annotations

from app.services.dag_orchestrator import (
    DAGStage,
    StageStatus,
    _reset_to_stage,
    _extract_rejection_feedback,
)


# ─────────────────────────────────────────────────────────────────────
# _extract_rejection_feedback — regex helper
# ─────────────────────────────────────────────────────────────────────


def test_extract_feedback_with_reason_marker():
    """The contract format: ``REASON: <text>`` after REJECT_TO."""
    out = (
        "REJECTED\n"
        "REJECT_TO: development\n"
        "REASON: 接口未做权限校验，登录后即可调用 /admin/users。"
    )
    fb = _extract_rejection_feedback(out)
    assert fb is not None
    assert "权限校验" in fb
    assert "/admin/users" in fb


def test_extract_feedback_multiline_reason():
    """REASON content runs to end-of-message and may span lines."""
    out = (
        "REJECTED\n"
        "REJECT_TO: testing\n"
        "REASON:\n"
        "1. 测试用例没覆盖空字符串场景\n"
        "2. 没有验证密码错误次数限制\n"
        "3. 缺少 JWT 过期场景的回归"
    )
    fb = _extract_rejection_feedback(out)
    assert fb is not None
    assert "空字符串" in fb
    assert "密码错误次数" in fb
    assert "JWT 过期" in fb


def test_extract_feedback_falls_back_to_post_rejected_block():
    """When reviewer skips the REASON marker, take everything after
    the REJECTED keyword as the reason."""
    out = (
        "REJECTED\n"
        "需求理解偏差，本轮 PRD 漏掉了管理员场景。"
    )
    fb = _extract_rejection_feedback(out)
    assert fb is not None
    assert "管理员场景" in fb


def test_extract_feedback_truncates_huge_payloads():
    """An over-talkative reviewer shouldn't be able to stuff 100KB
    into the next prompt."""
    huge = "x" * 50000
    out = f"REJECTED\nREASON: {huge}"
    fb = _extract_rejection_feedback(out)
    assert fb is not None
    assert len(fb) <= 8000


def test_extract_feedback_handles_empty_or_none():
    assert _extract_rejection_feedback("") is None
    assert _extract_rejection_feedback(None) is None  # type: ignore[arg-type]


def test_extract_feedback_chinese_full_width_colon():
    """Chinese content commonly uses ``REASON：`` (full-width colon)
    — the regex accepts both."""
    out = "REJECTED\nREJECT_TO: planning\nREASON：需求边界不清晰。"
    fb = _extract_rejection_feedback(out)
    assert fb is not None
    assert "需求边界不清晰" in fb


# ─────────────────────────────────────────────────────────────────────
# _reset_to_stage — feedback stamping
# ─────────────────────────────────────────────────────────────────────


def _build_stages():
    """Mini DAG: planning → development → testing → reviewing."""
    return [
        DAGStage("planning", "P", "pm"),
        DAGStage("development", "D", "dev", depends_on=["planning"]),
        DAGStage("testing", "T", "qa", depends_on=["development"]),
        DAGStage("reviewing", "R", "acceptance", depends_on=["testing"]),
    ]


def test_reset_to_stage_without_feedback_leaves_field_empty():
    """Back-compat: callers that don't pass ``feedback=`` keep the
    pre-self-heal behaviour (status reset only, no prompt patch)."""
    stages = _build_stages()
    for s in stages:
        s.status = StageStatus.DONE
        s.output = "old"

    _reset_to_stage(stages, "development")

    dev = next(s for s in stages if s.stage_id == "development")
    assert dev.status == StageStatus.PENDING
    assert dev.output is None
    assert dev.reject_feedback is None
    assert dev.reject_count == 0


def test_reset_to_stage_with_feedback_stamps_target():
    """Feedback lands on the target stage, not on its downstream."""
    stages = _build_stages()
    for s in stages:
        s.status = StageStatus.DONE
        s.output = "old"

    _reset_to_stage(
        stages, "development",
        feedback="缺少权限校验",
    )

    dev = next(s for s in stages if s.stage_id == "development")
    test = next(s for s in stages if s.stage_id == "testing")

    assert dev.reject_feedback == "缺少权限校验"
    assert dev.reject_count == 1
    # Downstream stage is reset but does NOT get the feedback —
    # that's specifically the rejected stage's responsibility.
    assert test.reject_feedback is None
    assert test.status == StageStatus.PENDING


def test_reset_to_stage_increments_reject_count_on_repeat():
    """Same stage rejected twice → ``reject_count`` reflects it. The
    UI can use this to flag "this stage keeps failing review" loops."""
    stages = _build_stages()
    for s in stages:
        s.status = StageStatus.DONE

    _reset_to_stage(stages, "development", feedback="round 1")
    # simulate the dev stage running and being rejected again
    dev = next(s for s in stages if s.stage_id == "development")
    dev.status = StageStatus.DONE
    _reset_to_stage(stages, "development", feedback="round 2")

    assert dev.reject_count == 2
    assert dev.reject_feedback == "round 2"  # latest feedback wins


def test_reset_to_unknown_stage_is_noop():
    """Defensive: a typo in REJECT_TO shouldn't blow up the DAG."""
    stages = _build_stages()
    for s in stages:
        s.status = StageStatus.DONE

    # should not raise
    _reset_to_stage(stages, "this-stage-does-not-exist", feedback="x")

    # all stages remain DONE
    assert all(s.status == StageStatus.DONE for s in stages)
