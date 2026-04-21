"""CLI entry: ``python -m scripts.swebench --help``.

Examples (run from the ``backend/`` directory)::

    # Smoke run on a tiny local fixture (no LLM, no docker, no network)
    PYTHONPATH=. uv run python -m scripts.swebench \
        --source tests/unit/fixtures/swebench_sample.jsonl \
        --dry-run

    # Single instance, full pipeline (needs LLM key + git + docker)
    PYTHONPATH=. uv run python -m scripts.swebench \
        --source hf:princeton-nlp/SWE-bench_Lite \
        --only django__django-15814 \
        --model claude-sonnet-4-5

    # Full Lite run, 4-way parallel, write per-instance JSON to ./swebench_runs
    PYTHONPATH=. uv run python -m scripts.swebench \
        --source hf:princeton-nlp/SWE-bench_Lite \
        --output-dir ./swebench_runs \
        --concurrency 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent import AgentAttempt, run_agentless_attempt
from .dataset import SweInstance, load_instances
from .evaluator import InstanceResult, evaluate_patch
from .repo_workspace import RepoWorkspace

logger = logging.getLogger("swebench")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.swebench",
                                description="Run agent-hub against SWE-Bench instances.")
    p.add_argument("--source", required=True,
                   help="Local JSONL path or 'hf:<repo>[:<split>]' (e.g. hf:princeton-nlp/SWE-bench_Lite).")
    p.add_argument("--only", action="append", default=None,
                   help="Restrict to one or more instance_ids (repeat the flag).")
    p.add_argument("--limit", type=int, default=None, help="Stop after N instances (post-filter).")
    p.add_argument("--workspace-root", default="./swebench_workspaces",
                   help="Directory for git caches + per-instance worktrees.")
    p.add_argument("--output-dir", default="./swebench_runs",
                   help="Directory for per-instance JSON results + summary.json.")
    p.add_argument("--concurrency", type=int, default=1, help="Run N instances in parallel.")
    p.add_argument("--model", default=os.getenv("SWEBENCH_MODEL", "claude-sonnet-4-5"),
                   help="LLM model id passed to chat_completion.")
    p.add_argument("--api-url", default=os.getenv("SWEBENCH_API_URL", ""),
                   help="Override API URL for chat_completion (otherwise uses provider default).")
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--test-timeout", type=int, default=600,
                   help="Seconds to allow the test runner per instance.")
    p.add_argument("--setup-cmd", default=None,
                   help="Shell command run inside the worktree before tests "
                        "(e.g. 'pip install --user -e .' to install the repo's deps). "
                        "Failures here mark the instance as 'apply_ok=True, resolved=False, error=setup-failed'.")
    p.add_argument("--test-command", default=None,
                   help="Override the default `python -m pytest` invocation. "
                        "Use {tests} placeholder to inject the FAIL_TO_PASS+PASS_TO_PASS list.")
    p.add_argument("--allow-local-exec", action="store_true",
                   help="Allow running tests on host if Docker is unavailable. Footgun for full runs.")
    p.add_argument("--no-docker", action="store_true",
                   help="Force local execution and skip Docker entirely. "
                        "Required for SWE-Bench until per-repo Docker images are wired up "
                        "(the default `python:3.11-slim` fallback has nothing installed).")
    p.add_argument("--docker-image", default=None,
                   help="Override the Docker image used by docker_sandbox.docker_exec.")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip LLM + evaluator; just load + verify instance shape. Useful for CI.")
    p.add_argument(
        "--use-gold-patch",
        action="store_true",
        help=(
            "Skip the LLM; feed the dataset's *gold* patch into the evaluator. "
            "Useful as an upper-bound sanity check: if a gold-patch run doesn't resolve, "
            "the evaluator (not the model) is broken."
        ),
    )
    p.add_argument("--verbose", action="store_true")
    return p


async def _amain(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    instances = load_instances(args.source, limit=args.limit, only_ids=args.only)
    if not instances:
        logger.error("no instances loaded from source=%s", args.source)
        return 2
    logger.info("loaded %d SWE-Bench instances", len(instances))

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for inst in instances:
            logger.info("[dry-run] %s | repo=%s | base=%s | f2p=%d | p2p=%d",
                        inst.instance_id, inst.repo, inst.base_commit[:7],
                        len(inst.fail_to_pass), len(inst.pass_to_pass))
        (out_dir / "summary.json").write_text(json.dumps({
            "dry_run": True,
            "instance_count": len(instances),
            "source": args.source,
        }, indent=2))
        return 0

    ws = RepoWorkspace(root=args.workspace_root)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    summary: List[Dict[str, Any]] = []

    started = time.monotonic()

    async def _one(inst: SweInstance) -> Dict[str, Any]:
        async with semaphore:
            return await _process_instance(inst, ws, args, out_dir)

    coros = [_one(inst) for inst in instances]
    for fut in asyncio.as_completed(coros):
        rec = await fut
        summary.append(rec)
        logger.info(
            "[done %d/%d] %s | resolved=%s | apply_ok=%s | engine=%s | %.1fs",
            len(summary), len(instances),
            rec["instance_id"], rec.get("resolved"), rec.get("apply_ok"),
            rec.get("engine"), rec.get("duration_s", 0.0),
        )

    summary_path = out_dir / "summary.json"
    resolved = sum(1 for r in summary if r.get("resolved"))
    summary_path.write_text(json.dumps({
        "source": args.source,
        "model": args.model,
        "instance_count": len(instances),
        "resolved": resolved,
        "resolved_pct": round(100.0 * resolved / max(1, len(instances)), 2),
        "duration_s": round(time.monotonic() - started, 1),
        "results": summary,
    }, indent=2))
    logger.info("summary -> %s | %d/%d resolved (%.1f%%)",
                summary_path, resolved, len(instances),
                100.0 * resolved / max(1, len(instances)))
    return 0


async def _process_instance(
    inst: SweInstance,
    ws: RepoWorkspace,
    args: argparse.Namespace,
    out_dir: Path,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {"instance_id": inst.instance_id}
    try:
        async with ws.checkout(inst) as layout:
            if args.use_gold_patch:
                if not inst.patch:
                    record["resolved"] = False
                    record["error"] = "instance has no gold patch"
                    _persist(record, None, None, out_dir)
                    return record
                from .patch_utils import patch_stats
                attempt = AgentAttempt(
                    instance_id=inst.instance_id,
                    patch=inst.patch if inst.patch.endswith("\n") else inst.patch + "\n",
                    stats=patch_stats(inst.patch),
                    selected_files=[],
                    raw_responses=[],
                    token_usage={},
                )
            else:
                llm = _build_llm_callable(model=args.model, api_url=args.api_url,
                                          max_tokens=args.max_tokens, temperature=args.temperature)
                attempt = await run_agentless_attempt(
                    instance_id=inst.instance_id,
                    problem_statement=inst.problem_statement,
                    repo_dir=layout.repo_dir,
                    llm=llm,
                )
            record["agent"] = {
                "engine": "gold-patch" if args.use_gold_patch else "agentless",
                "ok": attempt.ok,
                "selected_files": attempt.selected_files,
                "stats": {
                    "files_changed": attempt.stats.files_changed,
                    "hunks": attempt.stats.hunks,
                    "additions": attempt.stats.additions,
                    "deletions": attempt.stats.deletions,
                },
                "error": attempt.error,
                "token_usage": attempt.token_usage,
            }
            if not attempt.ok or attempt.patch is None:
                record["resolved"] = False
                record["apply_ok"] = False
                record["error"] = attempt.error or "agent produced no usable patch"
                _persist(record, attempt, None, out_dir)
                return record

            evaluator_result: InstanceResult = await evaluate_patch(
                instance=inst,
                patch_text=attempt.patch,
                repo_dir=layout.repo_dir,
                timeout_s=args.test_timeout,
                allow_local_exec=args.allow_local_exec or args.no_docker,
                docker_image=args.docker_image,
                force_local=args.no_docker,
                setup_cmd=args.setup_cmd,
                test_command=args.test_command,
            )
            record.update(evaluator_result.to_dict())
            _persist(record, attempt, evaluator_result, out_dir)
            return record
    except Exception as exc:
        logger.exception("[%s] processing crashed", inst.instance_id)
        record["resolved"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        _persist(record, None, None, out_dir)
        return record


def _persist(
    record: Dict[str, Any],
    attempt: Optional[AgentAttempt],
    result: Optional[InstanceResult],
    out_dir: Path,
) -> None:
    inst_dir = out_dir / record["instance_id"]
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "result.json").write_text(json.dumps(record, indent=2))
    if attempt and attempt.patch:
        (inst_dir / "agent.patch").write_text(attempt.patch)
    if attempt:
        for i, raw in enumerate(attempt.raw_responses):
            (inst_dir / f"llm_response_{i}.txt").write_text(raw or "")


def _build_llm_callable(*, model: str, api_url: str, max_tokens: int, temperature: float):
    """Late import so dry-run mode never imports the FastAPI app."""
    from app.services.llm_router import chat_completion  # type: ignore

    async def _call(_phase: str, messages):
        return await chat_completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            api_url=api_url,
        )

    return _call


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
