"""Background scheduler that periodically refreshes the GitHub
skill registry.

Design choices worth calling out:

- **Plain asyncio, not APScheduler.** We already live inside an asyncio
  event loop (FastAPI lifespan); a single ``asyncio.create_task`` with
  a sleep loop is ~30 lines and has no new deps. APScheduler only
  earns its weight if we grow multiple cron-like jobs; at that point
  we can swap the implementation behind the same ``start`` / ``stop``
  surface without touching callers.

- **Crawler runs in a thread.** ``httpx.Client`` (sync) is used by the
  crawler script so we don't have to maintain two network stacks. We
  wrap the work in ``asyncio.to_thread`` so the HTTP calls don't block
  the event loop; an ~60 s crawl goes into a worker thread.

- **Guarded by env flag.** Disabled by default (opt-in via
  ``SKILL_CRAWLER_ENABLED=1``) so dev/CI don't silently hit the
  GitHub API on every `make dev`. Token source defaults to
  ``GITHUB_TOKEN`` / ``GH_TOKEN`` / ``gh auth token``.

- **Jittered schedule.** Multi-instance deployments shouldn't all hit
  GitHub at the same wall-clock minute; we add ±10% random jitter to
  the sleep interval.

- **Refresh-in-process.** After a successful crawl we also invalidate
  ``skill_registry._registry_cache`` so the UI picks up the new data
  without a manual refresh.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Config via env so ops can tune without redeploying:
_ENV_FLAG = "SKILL_CRAWLER_ENABLED"             # "1" to turn on
_ENV_INTERVAL = "SKILL_CRAWLER_INTERVAL_HOURS"  # default 24
_ENV_INITIAL_DELAY = "SKILL_CRAWLER_INITIAL_DELAY_SEC"  # default 120

_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _resolve_token() -> Optional[str]:
    """Best-effort GitHub token lookup — env first, then gh CLI."""
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    # gh CLI fallback — useful on developer machines running `make dev`
    # without any token exported. Harmless on servers (just returns "").
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                return token
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _run_crawler_blocking(enable_topic_search: bool = False) -> tuple[bool, str]:
    """Execute ``crawl_github_skills.py`` as a subprocess.

    Runs via ``sys.executable`` so we inherit the venv / pyenv the
    backend is using. Uses subprocess instead of importing the module
    so any long-lived state (httpx client, rate-limit sleeps) is
    isolated and a crawler crash never takes down the backend.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    script = repo_root / "backend" / "scripts" / "crawl_github_skills.py"
    if not script.exists():
        return False, f"crawler script missing at {script}"

    env = os.environ.copy()
    token = _resolve_token()
    if token:
        env["GITHUB_TOKEN"] = token

    cmd = [sys.executable, str(script)]
    if enable_topic_search:
        cmd.append("--enable-topic-search")

    logger.info("skill-crawler: launching %s (topic_search=%s)", script.name, enable_topic_search)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "crawler timed out after 5 minutes"

    tail = (result.stdout or "").splitlines()[-12:]
    summary = "\n".join(tail)
    if result.returncode != 0:
        return False, f"crawler exit={result.returncode}\n{summary}\n{result.stderr[-400:]}"
    return True, summary


async def run_once(enable_topic_search: bool = False) -> tuple[bool, str]:
    """Public API — run one crawl + refresh the in-proc registry cache.

    Invoked both by the scheduler loop and by the admin
    ``POST /marketplace/crawl`` endpoint.
    """
    ok, msg = await asyncio.to_thread(_run_crawler_blocking, enable_topic_search)
    if ok:
        # Defer import to avoid a circular dep at module load time.
        from . import skill_registry
        skill_registry.refresh_registry_cache()
        logger.info("skill-crawler: ✓ complete\n%s", msg)
    else:
        logger.warning("skill-crawler: ✗ failed\n%s", msg)
    return ok, msg


async def _loop(interval_sec: float, initial_delay_sec: float) -> None:
    assert _stop_event is not None
    try:
        logger.info("skill-crawler: first run in %.0fs, then every %.1fh",
                    initial_delay_sec, interval_sec / 3600)
        # Wait for initial delay (but honour stop events instantly).
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=initial_delay_sec)
            return  # stopped before first run
        except asyncio.TimeoutError:
            pass

        while not _stop_event.is_set():
            try:
                await run_once()
            except Exception as exc:
                logger.exception("skill-crawler: unhandled error: %s", exc)
            # ±10% jitter so multi-instance deploys stagger their hits.
            jittered = interval_sec * (1 + random.uniform(-0.1, 0.1))
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=jittered)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        logger.info("skill-crawler: task cancelled")
        raise


def start() -> None:
    """Spawn the background crawler loop if enabled via env."""
    global _task, _stop_event
    if _task is not None:
        return  # already running — idempotent for hot reload

    if os.environ.get(_ENV_FLAG, "").strip().lower() not in ("1", "true", "yes"):
        logger.info("skill-crawler: disabled (set %s=1 to enable)", _ENV_FLAG)
        return

    try:
        hours = float(os.environ.get(_ENV_INTERVAL, "24"))
        initial = float(os.environ.get(_ENV_INITIAL_DELAY, "120"))
    except ValueError:
        logger.warning("skill-crawler: invalid interval env vars — using defaults")
        hours, initial = 24.0, 120.0

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_loop(hours * 3600, initial))


async def stop() -> None:
    """Signal the loop to exit and wait up to 5 s for a clean shutdown."""
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        except Exception:
            pass
    _task = None
    _stop_event = None
