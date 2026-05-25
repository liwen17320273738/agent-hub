"""
Outcome Contract — service + API tests.

Two sections:

1. ``TestOutcomeContractService`` — pure functions (validate, evaluate,
   aggregate, compute verdict). No DB or HTTP. These are the fast tests.
2. ``TestOutcomeContractAPI`` — end-to-end via FastAPI test client:
   draft → propose → sign → record → checkpoint → fulfilled / breached.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.outcome_contract_service import (
    ReadingPoint,
    aggregate_readings_for_metric,
    compute_checkpoint_verdict,
    evaluate_metric,
    validate_metric_def,
    validate_metrics_list,
    validate_verification_plan,
)


# ===========================================================================
# 1. Pure-function service tests
# ===========================================================================


class TestOutcomeContractService:

    def test_validate_metric_def_ok(self):
        metric = {
            "name": "weekly_active_users",
            "source": "plausible",
            "target_value": 500,
            "direction": "increase",
            "measurement_window_days": 30,
        }
        assert validate_metric_def(metric) == []

    def test_validate_metric_def_missing_keys(self):
        errs = validate_metric_def({"name": "x"})
        assert any("missing:source" in e for e in errs)
        assert any("missing:target_value" in e for e in errs)
        assert any("missing:direction" in e for e in errs)

    def test_validate_metric_def_bad_direction(self):
        errs = validate_metric_def({
            "name": "x", "source": "manual", "target_value": 1, "direction": "sideways",
        })
        assert any("bad_direction:sideways" in e for e in errs)

    def test_validate_metric_def_bad_target(self):
        errs = validate_metric_def({
            "name": "x", "source": "manual", "target_value": "not-a-number",
            "direction": "increase",
        })
        assert "bad_target_value" in errs

    def test_validate_metric_def_bad_window(self):
        errs = validate_metric_def({
            "name": "x", "source": "manual", "target_value": 1,
            "direction": "increase", "measurement_window_days": 0,
        })
        assert "bad_window" in errs

    def test_validate_metrics_list_empty(self):
        assert validate_metrics_list([]) == ["empty_metrics"]

    def test_validate_metrics_list_duplicate_name(self):
        m = {"name": "wau", "source": "manual", "target_value": 1, "direction": "increase"}
        errs = validate_metrics_list([m, m])
        assert any("duplicate_name:wau" in e for e in errs)

    def test_validate_verification_plan_empty(self):
        assert validate_verification_plan([]) == ["empty_plan"]

    def test_validate_verification_plan_duplicate_day(self):
        errs = validate_verification_plan([{"day": 30}, {"day": 30}])
        assert any("duplicate_day:30" in e for e in errs)

    def test_validate_verification_plan_bad_day(self):
        errs = validate_verification_plan([{"day": 0}, {"day": "abc"}])
        assert any("bad_day" in e for e in errs)

    # ── evaluate_metric ─────────────────────────────────────────────────

    def test_evaluate_metric_increase_pass(self):
        m = {"name": "wau", "target_value": 100, "direction": "increase"}
        result = evaluate_metric(m, 150)
        assert result["passed"] is True
        assert result["ratio"] == 1.5
        assert result["missing_reading"] is False

    def test_evaluate_metric_increase_fail(self):
        m = {"name": "wau", "target_value": 100, "direction": "increase"}
        result = evaluate_metric(m, 50)
        assert result["passed"] is False
        assert result["ratio"] == 0.5

    def test_evaluate_metric_decrease_pass(self):
        m = {"name": "churn", "target_value": 5, "direction": "decrease"}
        result = evaluate_metric(m, 3)
        assert result["passed"] is True
        # ratio = target / actual when decreasing — 5/3 ≈ 1.67, "we beat the target"
        assert result["ratio"] is not None and result["ratio"] > 1

    def test_evaluate_metric_decrease_fail(self):
        m = {"name": "churn", "target_value": 5, "direction": "decrease"}
        result = evaluate_metric(m, 10)
        assert result["passed"] is False

    def test_evaluate_metric_missing_reading(self):
        m = {"name": "wau", "target_value": 100, "direction": "increase"}
        result = evaluate_metric(m, None)
        assert result["passed"] is False
        assert result["missing_reading"] is True
        assert result["actual"] is None

    # ── aggregate_readings_for_metric ─────────────────────────────────

    def test_aggregate_picks_latest_in_window(self):
        now = datetime(2026, 6, 1, 12, 0, 0)
        m = {"name": "wau", "measurement_window_days": 30}
        readings = [
            ReadingPoint("wau", 100.0, now - timedelta(days=29)),
            ReadingPoint("wau", 200.0, now - timedelta(days=10)),
            ReadingPoint("wau", 150.0, now - timedelta(days=2)),
            ReadingPoint("other_metric", 999.0, now - timedelta(days=1)),
        ]
        assert aggregate_readings_for_metric(m, readings, window_end=now) == 150.0

    def test_aggregate_returns_none_when_outside_window(self):
        now = datetime(2026, 6, 1)
        m = {"name": "wau", "measurement_window_days": 7}
        readings = [
            ReadingPoint("wau", 999.0, now - timedelta(days=30)),
        ]
        assert aggregate_readings_for_metric(m, readings, window_end=now) is None

    # ── compute_checkpoint_verdict ────────────────────────────────────

    def test_verdict_all_pass(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
            {"name": "conversion", "source": "manual", "target_value": 0.05,
             "direction": "increase", "measurement_window_days": 30},
        ]
        readings = [
            ReadingPoint("wau", 150.0, now - timedelta(days=1)),
            ReadingPoint("conversion", 0.08, now - timedelta(days=1)),
        ]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=readings, refund_trigger={}, window_end=now,
        )
        assert v.verdict == "passed"
        assert v.refund_triggered is False
        assert "2/2 metrics passed" in v.summary

    def test_verdict_all_fail_triggers_default_refund(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
        ]
        readings = [ReadingPoint("wau", 50.0, now - timedelta(days=1))]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=readings, refund_trigger={}, window_end=now,
        )
        assert v.verdict == "failed"
        # Default trigger refunds when "no metric passed".
        assert v.refund_triggered is True
        assert "all_metrics_failed" in v.refund_reason

    def test_verdict_partial(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
            {"name": "conv", "source": "manual", "target_value": 0.05,
             "direction": "increase", "measurement_window_days": 30},
        ]
        readings = [
            ReadingPoint("wau", 150.0, now - timedelta(days=1)),
            ReadingPoint("conv", 0.02, now - timedelta(days=1)),
        ]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=readings, refund_trigger={}, window_end=now,
        )
        assert v.verdict == "partial"
        # Default trigger does NOT fire on partial (at least one passed).
        assert v.refund_triggered is False

    def test_verdict_any_metric_failed_trigger_fires_on_partial(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
            {"name": "conv", "source": "manual", "target_value": 0.05,
             "direction": "increase", "measurement_window_days": 30},
        ]
        readings = [
            ReadingPoint("wau", 150.0, now - timedelta(days=1)),
            ReadingPoint("conv", 0.02, now - timedelta(days=1)),
        ]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=readings,
            refund_trigger={"trigger": "any_metric_failed"},
            window_end=now,
        )
        assert v.verdict == "partial"
        assert v.refund_triggered is True
        assert "any_metric_failed:conv" in v.refund_reason

    def test_verdict_ratio_below_trigger(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
        ]
        readings = [ReadingPoint("wau", 30.0, now - timedelta(days=1))]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=readings,
            refund_trigger={"trigger": "ratio_below", "ratio": 0.5},
            window_end=now,
        )
        assert v.verdict == "failed"
        assert v.refund_triggered is True
        assert "ratio_below" in v.refund_reason

    def test_verdict_missing_readings_counts_as_failed(self):
        now = datetime(2026, 6, 1)
        metrics = [
            {"name": "wau", "source": "manual", "target_value": 100,
             "direction": "increase", "measurement_window_days": 30},
        ]
        v = compute_checkpoint_verdict(
            metrics=metrics, readings=[], refund_trigger={}, window_end=now,
        )
        assert v.verdict == "failed"
        assert v.metric_results[0]["missing_reading"] is True
        assert "1 metric(s) had no readings in window" in v.summary


# ===========================================================================
# 2. API integration tests
# ===========================================================================


def _draft_payload(task_id: str, **overrides):
    base = {
        "task_id": task_id,
        "business_goal": "Increase weekly active users for the new dashboard.",
        "success_metrics": [
            {
                "name": "weekly_active_users",
                "source": "manual",
                "target_value": 500,
                "direction": "increase",
                "measurement_window_days": 30,
                "baseline_value": 100,
            },
        ],
        "verification_plan": [
            {"day": 30, "method": "auto_metric_check"},
            {"day": 60, "method": "auto_metric_check"},
        ],
        "refund_policy": "full",
        "refund_trigger": {"trigger": "all_metrics_failed"},
        "price_usd": 10000.0,
        "deposit_pct": 0.3,
        "drafted_by_agent": "ceo-agent",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
class TestOutcomeContractAPI:

    async def test_draft_happy_path(self, client, sample_task_id):
        res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "draft"
        assert body["task_id"] == sample_task_id
        assert body["drafted_at"] is not None
        assert len(body["success_metrics"]) == 1

    async def test_draft_task_not_found(self, client):
        res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload("00000000-0000-0000-0000-000000000000"),
        )
        assert res.status_code == 404

    async def test_draft_duplicate_contract_409(self, client, sample_task_id):
        await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        assert res.status_code == 409

    async def test_draft_invalid_metrics_422(self, client, sample_task_id):
        payload = _draft_payload(sample_task_id)
        payload["success_metrics"] = [
            {
                "name": "wau", "source": "manual", "target_value": 100,
                "direction": "increase",
            },
            {
                "name": "wau", "source": "manual", "target_value": 200,
                "direction": "increase",
            },  # duplicate
        ]
        res = await client.post(
            "/api/outcome-contracts/draft", json=payload,
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "invalid_metrics" in detail
        assert "duplicate_name:wau" in detail

    async def test_draft_bad_source_422(self, client, sample_task_id):
        payload = _draft_payload(sample_task_id)
        payload["success_metrics"][0]["source"] = "made_up_source"
        res = await client.post(
            "/api/outcome-contracts/draft", json=payload,
        )
        assert res.status_code == 422
        assert "bad_metric_source" in res.json()["detail"]

    async def test_propose_flips_status(self, client, sample_task_id):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]

        res = await client.post(f"/api/outcome-contracts/{cid}/propose")
        assert res.status_code == 200
        assert res.json()["status"] == "proposed"

        # Re-propose is invalid.
        res2 = await client.post(f"/api/outcome-contracts/{cid}/propose")
        assert res2.status_code == 409

    async def test_sign_materializes_checkpoints(self, client, sample_task_id):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]
        await client.post(f"/api/outcome-contracts/{cid}/propose")

        res = await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "signed"
        assert body["signed_at"] is not None
        assert len(body["checkpoints"]) == 2
        days = sorted(cp["day_offset"] for cp in body["checkpoints"])
        assert days == [30, 60]
        for cp in body["checkpoints"]:
            assert cp["verdict"] == "pending"
            assert cp["scheduled_for"] is not None

    async def test_record_metric_requires_evidence_when_manual(
        self, client, sample_task_id
    ):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        res = await client.post(
            f"/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": "weekly_active_users",
                "value": 250,
                "source": "manual",
            },
        )
        assert res.status_code == 422
        assert "manual_reading_requires_evidence_url" in res.json()["detail"]

    async def test_record_metric_rejects_undeclared(
        self, client, sample_task_id
    ):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        res = await client.post(
            f"/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": "undeclared_metric",
                "value": 100,
                "source": "manual",
                "evidence_url": "https://screenshot.example.com/a.png",
            },
        )
        assert res.status_code == 422
        assert "metric_not_declared:undeclared_metric" in res.json()["detail"]

    async def test_full_lifecycle_to_fulfilled(self, client, sample_task_id):
        """draft → propose → sign → record (passing) → run all checkpoints → fulfilled"""
        # Use single-checkpoint plan to make assertions cleaner.
        payload = _draft_payload(
            sample_task_id,
            verification_plan=[{"day": 30, "method": "auto_metric_check"}],
        )
        draft_res = await client.post(
            "/api/outcome-contracts/draft", json=payload,
        )
        assert draft_res.status_code == 201, draft_res.text
        cid = draft_res.json()["id"]

        await client.post(f"/api/outcome-contracts/{cid}/propose")
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        # Customer pushes a passing metric reading.
        rec = await client.post(
            f"/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": "weekly_active_users",
                "value": 800,  # target is 500
                "source": "manual",
                "evidence_url": "https://screenshot.example.com/wau.png",
            },
        )
        assert rec.status_code == 201, rec.text

        # Run the checkpoint.
        run = await client.post(
            f"/api/outcome-contracts/{cid}/checkpoints/30/run",
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["verdict"]["verdict"] == "passed"
        assert body["verdict"]["refund_triggered"] is False
        assert body["contract"]["status"] == "fulfilled"
        assert body["contract"]["fulfilled_at"] is not None

    async def test_full_lifecycle_to_breached(self, client, sample_task_id):
        """draft → sign → record (failing) → run → breached + refund."""
        payload = _draft_payload(
            sample_task_id,
            verification_plan=[{"day": 30, "method": "auto_metric_check"}],
        )
        draft_res = await client.post(
            "/api/outcome-contracts/draft", json=payload,
        )
        cid = draft_res.json()["id"]
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        # Customer pushes a FAILING reading (target 500, actual 200).
        await client.post(
            f"/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": "weekly_active_users",
                "value": 200,
                "source": "manual",
                "evidence_url": "https://screenshot.example.com/wau.png",
            },
        )

        run = await client.post(
            f"/api/outcome-contracts/{cid}/checkpoints/30/run",
        )
        assert run.status_code == 200
        body = run.json()
        assert body["verdict"]["verdict"] == "failed"
        assert body["verdict"]["refund_triggered"] is True
        assert body["contract"]["status"] == "breached"
        assert body["contract"]["breached_at"] is not None
        # Checkpoint must record the refund decision.
        cp = body["checkpoint"]
        assert cp["refund_decision"] == "trigger"

    async def test_run_checkpoint_with_no_readings_is_failed(
        self, client, sample_task_id
    ):
        payload = _draft_payload(
            sample_task_id,
            verification_plan=[{"day": 30, "method": "auto_metric_check"}],
        )
        draft_res = await client.post(
            "/api/outcome-contracts/draft", json=payload,
        )
        cid = draft_res.json()["id"]
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        run = await client.post(
            f"/api/outcome-contracts/{cid}/checkpoints/30/run",
        )
        assert run.status_code == 200
        body = run.json()
        assert body["verdict"]["verdict"] == "failed"
        # Missing readings count as failure → default trigger fires.
        assert body["verdict"]["refund_triggered"] is True
        assert body["contract"]["status"] == "breached"

    async def test_get_contract_and_by_task(self, client, sample_task_id):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]
        await client.post(
            f"/api/outcome-contracts/{cid}/sign",
            json={"signed_by_customer": "acme@example.com"},
        )

        # Direct fetch.
        res = await client.get(f"/api/outcome-contracts/{cid}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == cid
        assert "checkpoints" in body
        assert "readings_count_by_metric" in body

        # Fetch by task FK.
        res2 = await client.get(f"/api/outcome-contracts/by-task/{sample_task_id}")
        assert res2.status_code == 200
        assert res2.json()["id"] == cid

    async def test_record_metric_rejects_when_contract_in_draft(
        self, client, sample_task_id
    ):
        draft_res = await client.post(
            "/api/outcome-contracts/draft",
            json=_draft_payload(sample_task_id),
        )
        cid = draft_res.json()["id"]

        res = await client.post(
            f"/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": "weekly_active_users",
                "value": 250,
                "source": "manual",
                "evidence_url": "https://example.com/e.png",
            },
        )
        assert res.status_code == 409
        assert "contract_not_active" in res.json()["detail"]
