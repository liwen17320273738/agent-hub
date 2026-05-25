"""
Demo: walk through the full outcome-contract lifecycle against a live backend.

Two scenarios played end-to-end:

  Scenario A — 客户拿到了承诺的结果 → fulfilled
      draft → propose → sign → record passing metric → run checkpoint
      → verdict=passed, contract.status=fulfilled

  Scenario B — 客户没拿到承诺的结果 → breached, refund triggered
      draft → sign → record failing metric → run checkpoint
      → verdict=failed, refund_triggered=true, contract.status=breached

Each step prints a readable diff of the contract state so you can SEE what
"对结果负责" actually looks like in data.

Usage:
    cd backend && python3 scripts/demo_outcome_contract.py

Prerequisite: backend running on http://localhost:8000 with PG migrations
applied (the script will create one throwaway PipelineTask per scenario).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Any, Dict

import httpx

# Silence SQLAlchemy / asyncio / aiosqlite chatter for the fallback DB path
# — the demo is meant to read as a business narrative, not a query log.
for noisy in ("sqlalchemy.engine", "aiosqlite", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


BACKEND = os.environ.get("AGENTHUB_BACKEND", "http://localhost:8000")
PIPELINE_API_KEY = os.environ.get("PIPELINE_API_KEY", "")

# ── tiny ANSI helpers ───────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"


def _verdict_color(verdict: str) -> str:
    return {
        "passed": GREEN + BOLD,
        "failed": RED + BOLD,
        "partial": YELLOW + BOLD,
        "skipped": GRAY,
        "pending": GRAY,
    }.get(verdict, "")


def banner(text: str, color: str = MAGENTA) -> None:
    bar = "═" * (len(text) + 4)
    print(f"\n{color}{BOLD}╔{bar}╗")
    print(f"║  {text}  ║")
    print(f"╚{bar}╝{RESET}")


def step(idx: int, label: str, *, color: str = CYAN) -> None:
    print(f"\n{color}{BOLD}┌─ Step {idx}: {label}{RESET}")


def kv(label: str, value: Any, *, color: str = "") -> None:
    print(f"  {color}{label:<24}{RESET} {value}")


def show_contract(c: Dict[str, Any], *, full: bool = False) -> None:
    status_color = {
        "draft": GRAY,
        "proposed": YELLOW,
        "signed": CYAN,
        "in_delivery": CYAN,
        "verifying": YELLOW,
        "fulfilled": GREEN + BOLD,
        "breached": RED + BOLD,
        "refunded": RED + BOLD,
        "cancelled": GRAY,
    }.get(c.get("status", ""), "")

    kv("id", c["id"][:8] + "...")
    kv("status", f"{status_color}{c['status']}{RESET}")
    kv("business_goal", c["business_goal"][:60] + ("..." if len(c["business_goal"]) > 60 else ""))
    kv("refund_policy", c.get("refund_policy"))
    kv("price / deposit", f"${c.get('price_usd')} / {c.get('deposit_pct', 0)*100:.0f}% upfront")
    if c.get("drafted_at"):
        kv("drafted_at", c["drafted_at"][:19])
    if c.get("signed_at"):
        kv("signed_at", f"{GREEN}{c['signed_at'][:19]} by {c.get('signed_by_customer')}{RESET}")
    if c.get("fulfilled_at"):
        kv("fulfilled_at", f"{GREEN}{BOLD}{c['fulfilled_at'][:19]}{RESET}")
    if c.get("breached_at"):
        kv("breached_at", f"{RED}{BOLD}{c['breached_at'][:19]}{RESET}")

    if full and c.get("success_metrics"):
        print(f"  {DIM}── success_metrics ──{RESET}")
        for m in c["success_metrics"]:
            print(
                f"    · {m['name']}: {m['direction']} → target {m['target_value']}"
                f"  (baseline {m.get('baseline_value', '?')}, window {m.get('measurement_window_days', 30)}d, src={m['source']})"
            )

    if c.get("checkpoints"):
        print(f"  {DIM}── checkpoints ──{RESET}")
        for cp in c["checkpoints"]:
            verdict_color = {
                "pending": GRAY,
                "passed": GREEN + BOLD,
                "failed": RED + BOLD,
                "partial": YELLOW,
                "skipped": GRAY,
            }.get(cp["verdict"], "")
            print(
                f"    · day {cp['day_offset']}: {verdict_color}{cp['verdict']}{RESET}"
                f"  {DIM}({cp['summary'] or 'not yet executed'}){RESET}"
            )
            for mr in cp.get("metric_results", []) or []:
                ok = f"{GREEN}✓{RESET}" if mr["passed"] else f"{RED}✗{RESET}"
                actual = "—" if mr["actual"] is None else mr["actual"]
                ratio = f" (ratio {mr['ratio']:.2f})" if mr.get("ratio") else ""
                print(f"        {ok} {mr['metric']}: actual={actual} vs target={mr['target']}{ratio}")


async def create_throwaway_task(client: httpx.AsyncClient) -> str:
    """Create a PipelineTask via the pipeline API (or DB-direct fallback)."""
    if PIPELINE_API_KEY:
        res = await client.post(
            f"{BACKEND}/api/pipeline/tasks",
            headers={"Authorization": f"Bearer {PIPELINE_API_KEY}"},
            json={
                "title": "Outcome contract demo",
                "description": "Throwaway task for demo_outcome_contract.py",
                "source": "demo",
            },
        )
        if res.status_code in (200, 201):
            body = res.json()
            task = body.get("task") if isinstance(body, dict) else None
            if isinstance(task, dict) and task.get("id"):
                return task["id"]
            if isinstance(body, dict) and body.get("id"):
                return body["id"]

    # Silent DB-direct fallback (no PIPELINE_API_KEY in env).
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.database import async_session
    from app.models.pipeline import PipelineTask

    async with async_session() as s:
        task = PipelineTask(
            title="Outcome contract demo",
            description="Throwaway task used by demo_outcome_contract.py",
            source="demo",
            created_by="demo",
        )
        s.add(task)
        await s.commit()
        return str(task.id)


async def scenario_a_fulfilled(client: httpx.AsyncClient) -> None:
    banner("Scenario A — 拿到承诺的结果 → fulfilled", color=GREEN)

    task_id = await create_throwaway_task(client)
    kv("task_id", task_id[:8] + "...", color=DIM)

    step(1, "agent 草拟合同（一个 WAU 指标 + 30 天 checkpoint）")
    draft_payload = {
        "task_id": task_id,
        "business_goal": "30 天内把每周活跃用户从 100 提升到 500，达成则全额支付，未达成全额退款。",
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
        "verification_plan": [{"day": 30, "method": "auto_metric_check"}],
        "refund_policy": "full",
        "refund_trigger": {"trigger": "all_metrics_failed"},
        "price_usd": 10000.0,
        "deposit_pct": 0.3,
        "drafted_by_agent": "ceo-agent",
    }
    res = await client.post(f"{BACKEND}/api/outcome-contracts/draft", json=draft_payload)
    assert res.status_code == 201, res.text
    contract = res.json()
    cid = contract["id"]
    show_contract(contract, full=True)

    step(2, "客户签字")
    res = await client.post(
        f"{BACKEND}/api/outcome-contracts/{cid}/sign",
        json={"signed_by_customer": "founder@acme.example.com"},
    )
    assert res.status_code == 200, res.text
    contract = res.json()
    show_contract(contract)
    print(f"  {GREEN}→ {len(contract['checkpoints'])} 个 checkpoint 已自动生成（pending）{RESET}")

    step(3, "30 天后客户录入达标读数 (WAU=800，超目标)")
    res = await client.post(
        f"{BACKEND}/api/outcome-contracts/{cid}/record-metric",
        json={
            "metric_name": "weekly_active_users",
            "value": 800,
            "source": "manual",
            "evidence_url": "https://plausible.example.com/screenshot.png",
        },
    )
    assert res.status_code == 201, res.text
    reading = res.json()
    kv("recorded value", f"{GREEN}{reading['value']}{RESET}")
    kv("evidence_url", reading["evidence_url"], color=DIM)

    step(4, "跑 30 天 checkpoint —— 看判决")
    res = await client.post(f"{BACKEND}/api/outcome-contracts/{cid}/checkpoints/30/run")
    assert res.status_code == 200, res.text
    body = res.json()
    verdict = body["verdict"]
    v_color = _verdict_color(verdict["verdict"])
    kv("verdict", f"{v_color}{verdict['verdict']}{RESET}")
    kv("refund_triggered", verdict["refund_triggered"])
    kv("summary", verdict["summary"])
    print()
    show_contract(body["contract"])

    if verdict["verdict"] == "passed":
        print(
            f"\n  {GREEN}{BOLD}✓ 客户买到了真东西，钱归我们；下一步去做维护订阅。{RESET}"
        )
    else:
        print(
            f"\n  {RED}{BOLD}✗ 判决: {verdict['verdict']} — 出乎意料的结果，看 metric_results 复盘。{RESET}"
        )


async def scenario_b_breached(client: httpx.AsyncClient) -> None:
    banner("Scenario B — 没拿到承诺的结果 → breached + refund triggered", color=RED)

    task_id = await create_throwaway_task(client)
    kv("task_id", task_id[:8] + "...", color=DIM)

    step(1, "agent 草拟合同（任意指标失败就触发退款）")
    res = await client.post(
        f"{BACKEND}/api/outcome-contracts/draft",
        json={
            "task_id": task_id,
            "business_goal": "30 天达成两个指标：WAU 500、付费转化 ≥ 5%。任一未达成全额退款。",
            "success_metrics": [
                {
                    "name": "weekly_active_users",
                    "source": "manual",
                    "target_value": 500,
                    "direction": "increase",
                    "measurement_window_days": 30,
                    "baseline_value": 100,
                },
                {
                    "name": "paid_conversion",
                    "source": "manual",
                    "target_value": 0.05,
                    "direction": "increase",
                    "measurement_window_days": 30,
                    "baseline_value": 0.01,
                },
            ],
            "verification_plan": [{"day": 30, "method": "auto_metric_check"}],
            "refund_policy": "full",
            "refund_trigger": {"trigger": "any_metric_failed"},
            "price_usd": 10000.0,
            "deposit_pct": 0.3,
            "drafted_by_agent": "ceo-agent",
        },
    )
    assert res.status_code == 201, res.text
    contract = res.json()
    cid = contract["id"]
    show_contract(contract, full=True)

    step(2, "客户签字")
    res = await client.post(
        f"{BACKEND}/api/outcome-contracts/{cid}/sign",
        json={"signed_by_customer": "founder@acme.example.com"},
    )
    assert res.status_code == 200
    show_contract(res.json())

    step(3, "30 天后客户录入读数：WAU 达标 600 ✓ / 付费转化未达标 2% ✗")
    for name, value, ok in [
        ("weekly_active_users", 600, True),
        ("paid_conversion", 0.02, False),
    ]:
        res = await client.post(
            f"{BACKEND}/api/outcome-contracts/{cid}/record-metric",
            json={
                "metric_name": name,
                "value": value,
                "source": "manual",
                "evidence_url": f"https://screenshot.example.com/{name}.png",
            },
        )
        assert res.status_code == 201, res.text
        mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        kv(name, f"{mark} {value}")

    step(4, "跑 30 天 checkpoint —— 触发退款")
    res = await client.post(f"{BACKEND}/api/outcome-contracts/{cid}/checkpoints/30/run")
    assert res.status_code == 200, res.text
    body = res.json()
    verdict = body["verdict"]
    v_color = _verdict_color(verdict["verdict"])
    kv("verdict", f"{v_color}{verdict['verdict']}{RESET}")
    refund_color = RED + BOLD if verdict["refund_triggered"] else GREEN
    kv("refund_triggered", f"{refund_color}{verdict['refund_triggered']}{RESET}")
    kv("refund_reason", verdict["refund_reason"])
    kv("summary", verdict["summary"])
    print()
    show_contract(body["contract"])

    print(
        f"\n  {RED}{BOLD}✗ 我们没交付到位，钱要退；checkpoint 留下完整证据链给客户和我们自己复盘。{RESET}"
    )


async def show_global_state(client: httpx.AsyncClient) -> None:
    banner("最后看一眼全局合同列表 (GET /api/outcome-contracts/?limit=10)", color=CYAN)
    res = await client.get(f"{BACKEND}/api/outcome-contracts/?limit=10")
    if res.status_code != 200:
        print(f"{RED}列出失败: {res.text}{RESET}")
        return
    contracts = res.json()
    print(f"{DIM}共 {len(contracts)} 份合同（最近 10 份）{RESET}\n")
    for c in contracts[:10]:
        status_color = {
            "fulfilled": GREEN + BOLD,
            "breached": RED + BOLD,
            "signed": CYAN,
            "draft": GRAY,
        }.get(c["status"], YELLOW)
        print(
            f"  {c['id'][:8]}  {status_color}{c['status']:<11}{RESET}"
            f"  ${c.get('price_usd', 0):>8.0f}"
            f"  {c['business_goal'][:60]}"
        )


async def main() -> int:
    print(f"{BOLD}Outcome Contract Demo — backend = {BACKEND}{RESET}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            health = await client.get(f"{BACKEND}/health")
            health.raise_for_status()
        except Exception as exc:
            print(f"{RED}{BOLD}✗ Backend not reachable: {exc}{RESET}")
            print(f"{DIM}先跑: make dev{RESET}")
            return 2
        print(f"{GREEN}✓ Backend healthy{RESET}")

        try:
            await scenario_a_fulfilled(client)
            await scenario_b_breached(client)
            await show_global_state(client)
        except AssertionError as exc:
            print(f"\n{RED}{BOLD}✗ Step failed:{RESET} {exc}")
            return 1
        except Exception as exc:
            print(f"\n{RED}{BOLD}✗ Crash:{RESET} {type(exc).__name__}: {exc}")
            return 1

    print(
        f"\n{GREEN}{BOLD}═══ Demo done. 两条生命周期都跑通了，去看 PG 表确认数据落库。 ═══{RESET}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
