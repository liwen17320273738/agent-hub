#!/usr/bin/env python3
"""Hero slice baseline — single-task, quiet-environment timing probe.

Usage:
  cd backend && python3 ../scripts/hero_baseline.py
  cd backend && python3 ../scripts/hero_baseline.py --stage planning
  cd backend && python3 ../scripts/hero_baseline.py --full   # planning only for now

Writes docs/hero-baseline-latest.json with wall-clock, gate, token/cost hints.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "hero-baseline-latest.json"

BASE = os.getenv("AGENTHUB_API_BASE", "http://localhost:8000/api")
EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

PLANNING_TARGET_SEC = 90
REQ_TITLE = "Hero基线-纯前端待办看板"
REQ_DESC = "做一个纯前端待办看板：增删改查、本地存储、简洁 UI。不要后端。"


def _req(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 60):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:800]
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            payload = {"_error": body_text}
        return e.code, payload


def login() -> str:
    code, data = _req("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})
    if code != 200 or not data.get("access_token"):
        raise SystemExit(f"login failed ({code}): {data}")
    return data["access_token"]


def create_task(token: str) -> str:
    code, data = _req(
        "POST",
        "/pipeline/tasks",
        token=token,
        body={"title": REQ_TITLE, "description": REQ_DESC, "template": "web_app"},
    )
    if code not in (200, 201):
        raise SystemExit(f"create task failed ({code}): {data}")
    task = data.get("task") or data
    tid = task.get("id")
    if not tid:
        raise SystemExit(f"create task missing id: {data}")
    return str(tid)


def start_planning(token: str, task_id: str) -> None:
    code, data = _req(
        "POST",
        f"/pipeline/tasks/{task_id}/run-stage",
        token=token,
        body={"stageId": "planning"},
    )
    if code not in (200, 202):
        raise SystemExit(f"run-stage planning failed ({code}): {data}")


def fetch_task(token: str, task_id: str) -> dict:
    code, data = _req("GET", f"/pipeline/tasks/{task_id}", token=token)
    if code != 200:
        raise SystemExit(f"get task failed ({code}): {data}")
    return data.get("task") or data


def stage_snapshot(task: dict, stage_id: str) -> dict:
    for s in task.get("stages") or []:
        if s.get("stage_id") == stage_id or s.get("stageId") == stage_id:
            return s
    return {}


def poll_planning(token: str, task_id: str, timeout_sec: int = 600) -> dict:
    terminal = {"done", "failed", "blocked", "rejected", "skipped", "cancelled"}
    t0 = time.time()
    last_status = None
    while time.time() - t0 < timeout_sec:
        task = fetch_task(token, task_id)
        st = stage_snapshot(task, "planning")
        status = st.get("status") or "pending"
        if status != last_status:
            elapsed = round(time.time() - t0, 1)
            print(f"[{elapsed}s] planning status={status} gate={st.get('quality_gate_status')} q={st.get('quality_score')}")
            last_status = status
        if status in terminal:
            return {
                "elapsed_sec": round(time.time() - t0, 2),
                "task_status": task.get("status"),
                "stage": st,
                "task_id": task_id,
            }
        time.sleep(3)
    raise SystemExit(f"timeout after {timeout_sec}s waiting for planning")


def main() -> int:
    parser = argparse.ArgumentParser(description="Hero slice baseline probe")
    parser.add_argument("--stage", default="planning", help="stage to run (default: planning)")
    parser.add_argument("--full", action="store_true", help="reserved: full hero slice (future)")
    args = parser.parse_args()

    if args.stage != "planning" and not args.full:
        print("Only --stage planning is implemented in baseline v1", file=sys.stderr)

    print(f"API={BASE} email={EMAIL}")
    token = login()
    print("logged in")

    task_id = create_task(token)
    print(f"task created: {task_id}")

    t_start = time.time()
    start_planning(token, task_id)
    print("run-stage planning submitted")

    result = poll_planning(token, task_id)
    st = result["stage"]
    gate = st.get("quality_gate_status") or st.get("qualityGateStatus") or st.get("gate_status")
    gate_score = st.get("quality_gate_score") or st.get("qualityGateScore") or st.get("gate_score")
    elapsed = result["elapsed_sec"]
    passed_time = elapsed <= PLANNING_TARGET_SEC
    gate_ok = gate in ("passed", "warn", "pass") and st.get("status") == "done"
    honest_pause = st.get("status") in ("rejected", "failed", "blocked") and result["task_status"] == "paused"

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_id": task_id,
        "stage": "planning",
        "elapsed_sec": elapsed,
        "target_sec": PLANNING_TARGET_SEC,
        "passed_time": passed_time,
        "stage_status": st.get("status"),
        "task_status": result["task_status"],
        "quality_gate": gate,
        "quality_gate_score": gate_score,
        "quality_score": st.get("quality_score"),
        "gate_ok": gate_ok,
        "honest_pause": honest_pause,
        "overall_pass": passed_time and (gate_ok or honest_pause) and result["task_status"] in ("active", "done", "paused"),
        "requirement": REQ_DESC,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nwritten → {OUT_PATH}")
    print(f"wall-clock total (incl. setup): {round(time.time() - t_start, 1)}s")
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
