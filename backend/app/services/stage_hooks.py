"""Stage Hooks — pre_stage / post_stage extension points for Skills and plugins.

Hook registration is simple: call `register_hook(phase, stage_pattern, callback)`.
The pipeline calls `run_hooks("pre", stage_id, ctx)` before LLM and
`run_hooks("post", stage_id, ctx)` after output is written.

Built-in post-hooks:
  - code_extractor: extract code blocks from development/architecture output
  - test_validator: basic validation of test reports
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HookContext:
    task_id: str
    stage_id: str
    worktree: Optional[Path] = None
    content: str = ""
    model: str = ""
    agent_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


HookFn = Callable[[HookContext], Coroutine[Any, Any, Optional[Dict[str, Any]]]]


@dataclass
class _HookEntry:
    phase: str
    stage_pattern: str
    name: str
    fn: HookFn
    priority: int = 50


_hooks: List[_HookEntry] = []


def register_hook(
    phase: str,
    stage_pattern: str,
    fn: HookFn,
    *,
    name: str = "",
    priority: int = 50,
) -> None:
    """Register a hook. phase is 'pre' or 'post'. stage_pattern is a regex."""
    entry = _HookEntry(
        phase=phase,
        stage_pattern=stage_pattern,
        name=name or fn.__name__,
        fn=fn,
        priority=priority,
    )
    _hooks.append(entry)
    _hooks.sort(key=lambda h: h.priority)
    logger.debug("[hooks] Registered %s hook '%s' for stages matching '%s'",
                 phase, entry.name, stage_pattern)


async def run_hooks(phase: str, ctx: HookContext) -> List[Dict[str, Any]]:
    """Run all hooks matching the phase and stage. Returns list of results."""
    results: List[Dict[str, Any]] = []
    for entry in _hooks:
        if entry.phase != phase:
            continue
        if not re.match(entry.stage_pattern, ctx.stage_id):
            continue
        try:
            logger.info("[hooks] Running %s hook '%s' for stage '%s'",
                        phase, entry.name, ctx.stage_id)
            result = await entry.fn(ctx)
            results.append({"hook": entry.name, "ok": True, **(result or {})})
        except Exception as exc:
            logger.warning("[hooks] %s hook '%s' failed: %s", phase, entry.name, exc)
            results.append({"hook": entry.name, "ok": False, "error": str(exc)})
    return results


# ── Built-in Hooks ────────────────────────────────────────────────

async def _code_extractor_hook(ctx: HookContext) -> Optional[Dict[str, Any]]:
    """Extract code blocks from development output and write as real files."""
    if not ctx.worktree or not ctx.content:
        return {"skipped": True, "reason": "no worktree or content"}

    from .code_extractor import extract_code_blocks, write_extracted_files

    extraction = extract_code_blocks(ctx.content)
    if not extraction.files:
        return {"files_found": 0}

    created = await write_extracted_files(ctx.worktree, extraction)
    return {
        "files_found": len(extraction.files),
        "files_written": len(created),
        "total_bytes": extraction.total_bytes,
        "paths": created,
    }


async def _test_validator_hook(ctx: HookContext) -> Optional[Dict[str, Any]]:
    """Basic validation: check if test report mentions pass/fail counts."""
    if not ctx.content:
        return {"skipped": True}

    has_results = bool(re.search(
        r"(通过|passed|pass|成功|✅|PASS).*(失败|failed|fail|错误|❌|FAIL)|"
        r"(测试结果|test results|summary)",
        ctx.content,
        re.IGNORECASE,
    ))
    has_code = "```" in ctx.content

    return {
        "has_test_results": has_results,
        "has_code_blocks": has_code,
        "content_length": len(ctx.content),
    }


async def _deployment_extractor_hook(ctx: HookContext) -> Optional[Dict[str, Any]]:
    """Extract Docker / compose / shell snippets from deployment stage into deploy/."""
    if not ctx.worktree or not ctx.content:
        return {"skipped": True, "reason": "no worktree or content"}

    from .code_extractor import extract_code_blocks, write_extracted_files

    extraction = extract_code_blocks(ctx.content)
    if not extraction.files:
        return {"files_found": 0}

    deployish = [
        f for f in extraction.files
        if any(
            x in f.path.lower()
            for x in ("dockerfile", "compose", ".yaml", ".yml", ".sh", ".env", "nginx", "k8s", "kubernetes")
        ) or f.language.lower() in ("dockerfile", "yaml", "bash", "shell", "sh")
    ]
    if not deployish:
        deployish = extraction.files[:20]

    from .code_extractor import ExtractionResult
    sub = ExtractionResult(files=deployish, warnings=list(extraction.warnings))
    created = await write_extracted_files(ctx.worktree, sub, sub_dir="deploy")
    return {
        "files_found": len(deployish),
        "files_written": len(created),
        "paths": created,
    }


async def _architecture_extractor_hook(ctx: HookContext) -> Optional[Dict[str, Any]]:
    """Extract config/schema files from architecture stage output."""
    if not ctx.worktree or not ctx.content:
        return {"skipped": True}

    from .code_extractor import extract_code_blocks, write_extracted_files

    extraction = extract_code_blocks(ctx.content)
    config_files = [f for f in extraction.files
                    if any(f.path.endswith(ext) for ext in (".json", ".yaml", ".yml", ".toml", ".sql"))]

    if not config_files:
        return {"files_found": 0}

    from .code_extractor import ExtractionResult
    config_extraction = ExtractionResult(files=config_files)
    created = await write_extracted_files(ctx.worktree, config_extraction, sub_dir="config")
    return {
        "files_found": len(config_files),
        "files_written": len(created),
        "paths": created,
    }


def register_builtin_hooks() -> None:
    """Register all built-in hooks. Called once at startup."""
    register_hook("post", r"^development$", _code_extractor_hook,
                  name="code-extractor", priority=10)
    register_hook("post", r"^architecture$", _architecture_extractor_hook,
                  name="arch-config-extractor", priority=20)
    register_hook("post", r"^testing$", _test_validator_hook,
                  name="test-validator", priority=10)
    register_hook("post", r"^deployment$", _deployment_extractor_hook,
                  name="deployment-extractor", priority=15)
