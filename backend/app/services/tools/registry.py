"""
Tool Registry — central registry of all available agent tools.

Maps tool names to their implementations and provides a unified
execution interface with permission checking.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .file_tools import file_read, file_write, file_list, str_replace
from .bash_tool import bash_execute
from .web_search import web_search
from .git_tool import GIT_TOOL_DEFINITIONS, execute_git_tool
from .build_tool import build_project, install_dependencies, run_tests
from .test_runner import (
    run_tests as advanced_run_tests,
    detect_test_runner,
    format_test_report,
)
from .deerflow_tool import deerflow_delegate, deerflow_list_skills, deerflow_list_models

logger = logging.getLogger(__name__)

try:
    from .browser_tool import (
        browser_open, browser_screenshot, browser_extract, browser_click_flow,
    )
    _BROWSER_LOADED = True
except Exception as _be:  # noqa: BLE001
    logger.info(f"[tools] browser tools not available: {_be}")
    _BROWSER_LOADED = False

from .codebase_index import repo_map as _codebase_map, search_repo as _codebase_search, read_chunk as _codebase_read_chunk


async def _test_execute_handler(params: Dict[str, Any]) -> str:
    """Adapter: run structured test execution and return JSON report."""
    result = await advanced_run_tests(
        project_dir=params.get("project_dir", "."),
        runner=params.get("runner"),
        test_path=params.get("test_path"),
        extra_args=params.get("extra_args"),
        timeout=params.get("timeout", 300),
        env_vars=params.get("env_vars"),
    )
    result["report"] = format_test_report(result)
    return json.dumps(result, ensure_ascii=False, default=str)


async def _test_detect_handler(params: Dict[str, Any]) -> str:
    """Adapter: detect test runner and return JSON."""
    runner = detect_test_runner(params.get("project_dir", "."))
    return json.dumps({"ok": True, "runner": runner})

ToolFunc = Callable[[Dict[str, Any]], Coroutine[Any, Any, str]]

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "file_read": {
        "name": "file_read",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read (relative to workspace)"},
            },
            "required": ["path"],
        },
        "permissions": ["read"],
        "handler": file_read,
    },
    "file_write": {
        "name": "file_write",
        "description": "Write content to a file (creates parent directories if needed)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        "permissions": ["write"],
        "handler": file_write,
    },
    "file_list": {
        "name": "file_list",
        "description": "List files and directories at a given path",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list (default: '.')"},
            },
        },
        "permissions": ["read"],
        "handler": file_list,
    },
    "str_replace": {
        "name": "str_replace",
        "description": "Replace an exact string in a file with new content",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to find"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "permissions": ["write"],
        "handler": str_replace,
    },
    "bash": {
        "name": "bash",
        "description": "Execute a bash command in the sandbox workspace",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Max seconds (default: 30, max: 120)"},
            },
            "required": ["command"],
        },
        "permissions": ["execute"],
        "handler": bash_execute,
    },
    "web_search": {
        "name": "web_search",
        "description": "Search the web for information using DuckDuckGo",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Number of results (default: 5, max: 10)"},
            },
            "required": ["query"],
        },
        "permissions": ["network"],
        "handler": web_search,
    },
    # --- Build tools ---
    "build": {
        "name": "build",
        "description": "Build a project (auto-detects npm/pip/make or use preset)",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
                "command": {"type": "string", "description": "Custom build command (overrides auto-detect)"},
                "preset": {"type": "string", "description": "Build preset: npm, pnpm, pip, make"},
                "action": {"type": "string", "description": "Action: build, install, dev, test (default: build)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
            },
        },
        "permissions": ["execute"],
        "handler": build_project,
    },
    "install_deps": {
        "name": "install_deps",
        "description": "Install project dependencies (auto-detects package manager)",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
                "preset": {"type": "string", "description": "Build preset: npm, pnpm, pip, make"},
            },
        },
        "permissions": ["execute", "network"],
        "handler": install_dependencies,
    },
    "run_tests": {
        "name": "run_tests",
        "description": "Run project tests (auto-detects test runner)",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
                "preset": {"type": "string", "description": "Build preset: npm, pnpm, pip, make"},
            },
        },
        "permissions": ["execute"],
        "handler": run_tests,
    },
    # --- DeerFlow delegation tools ---
    "deerflow_delegate": {
        "name": "deerflow_delegate",
        "description": "Delegate a research/analysis/coding task to DeerFlow's multi-agent system. Returns DeerFlow's response. Use for deep research, complex analysis, or tasks requiring web browsing and code execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Task or question to send to DeerFlow"},
                "mode": {"type": "string", "description": "Execution mode: flash (fast), standard, pro (planning), ultra (sub-agents). Default: pro"},
                "thread_id": {"type": "string", "description": "Optional: continue an existing DeerFlow conversation"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
            },
            "required": ["message"],
        },
        "permissions": ["network"],
        "handler": deerflow_delegate,
    },
    "deerflow_skills": {
        "name": "deerflow_skills",
        "description": "List available skills from the connected DeerFlow instance",
        "parameters": {"type": "object", "properties": {}},
        "permissions": ["network"],
        "handler": deerflow_list_skills,
    },
    "deerflow_models": {
        "name": "deerflow_models",
        "description": "List available models from the connected DeerFlow instance",
        "parameters": {"type": "object", "properties": {}},
        "permissions": ["network"],
        "handler": deerflow_list_models,
    },
    # --- Advanced test tools (structured results with parsed output) ---
    "test_execute": {
        "name": "test_execute",
        "description": "Run tests with structured result parsing (pass/fail/skip counts, failure details, Markdown report). Supports pytest, jest, vitest, go test, cargo test.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": "Path to project root"},
                "runner": {"type": "string", "description": "Test runner (pytest/jest/vitest/go/cargo). Auto-detected if omitted."},
                "test_path": {"type": "string", "description": "Specific test file or directory to run"},
                "extra_args": {"type": "array", "items": {"type": "string"}, "description": "Extra CLI args for the test runner"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
            },
            "required": ["project_dir"],
        },
        "permissions": ["execute"],
        "handler": _test_execute_handler,
    },
    "test_detect": {
        "name": "test_detect",
        "description": "Auto-detect which test runner a project uses (pytest/jest/vitest/go/cargo)",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": "Path to project root"},
            },
            "required": ["project_dir"],
        },
        "permissions": ["read"],
        "handler": _test_detect_handler,
    },
}


TOOL_REGISTRY["codebase_map"] = {
    "name": "codebase_map",
    "description": (
        "Build a Markdown tree of an existing project (directories → files → "
        "top-level symbols). Use this FIRST when working on an unfamiliar "
        "codebase, before any file_read. Skips node_modules / dist / images."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string", "description": "Absolute or workspace-relative project root"},
            "max_files": {"type": "integer", "description": "Cap on indexed files (default from config)"},
            "output_limit": {"type": "integer", "description": "Max chars to return (default 10000)"},
        },
        "required": ["project_dir"],
    },
    "permissions": ["read"],
    "handler": _codebase_map,
}
TOOL_REGISTRY["codebase_search"] = {
    "name": "codebase_search",
    "description": (
        "Search a project for a literal string or regex; returns matched "
        "lines with file:line prefix. Uses ripgrep when available, pure-Python "
        "fallback otherwise. Use this BEFORE blindly file_read'ing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string"},
            "query": {"type": "string", "description": "Literal text or regex pattern"},
            "regex": {"type": "boolean", "description": "Treat query as regex (default false)"},
            "max_count": {"type": "integer", "description": "Max matches per file (default 5, max 50)"},
        },
        "required": ["project_dir", "query"],
    },
    "permissions": ["read"],
    "handler": _codebase_search,
}
TOOL_REGISTRY["codebase_read_chunk"] = {
    "name": "codebase_read_chunk",
    "description": "Read a slice of a file with line numbers. Use after codebase_search to drill into a hit.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string"},
            "path": {"type": "string", "description": "Path relative to project_dir"},
            "start": {"type": "integer", "description": "1-based start line (default 1)"},
            "end": {"type": "integer", "description": "1-based end line (default EOF)"},
        },
        "required": ["project_dir", "path"],
    },
    "permissions": ["read"],
    "handler": _codebase_read_chunk,
}


async def _semantic_search_handler(params: Dict[str, Any]) -> str:
    """Run semantic_search against the codebase index and format hits as Markdown.

    Late-imports the async DB session so registry import remains light.
    """
    from ..codebase_indexer import semantic_search
    from ...database import async_session as AsyncSessionLocal

    project_dir = (params.get("project_dir") or "").strip()
    project_id = (params.get("project_id") or project_dir or "").strip()
    query = (params.get("query") or "").strip()
    if not project_id or not query:
        return "Error: both 'project_dir' (or 'project_id') and 'query' are required"
    top_k = int(params.get("top_k") or 5)

    async with AsyncSessionLocal() as db:
        result = await semantic_search(
            db, project_id=project_id, query=query, top_k=top_k,
        )

    if not result.get("ok"):
        return f"Error: {result.get('error', 'unknown')}"
    hits = result.get("hits") or []
    if not hits:
        return f"(no semantic hits — index may be empty; run reindex first for project {project_id})"
    lines = [
        f"[code_semantic_search] query={query!r} scanned={result.get('scanned_chunks')} hits={len(hits)}",
        "",
    ]
    for i, h in enumerate(hits, 1):
        sym = (", ".join(h["symbols"][:5])) if h.get("symbols") else ""
        sym_part = f"  symbols: {sym}" if sym else ""
        lines.append(
            f"### {i}. `{h['rel_path']}:{h['start_line']}-{h['end_line']}`  "
            f"score={h['score']}{sym_part}"
        )
        lines.append("```")
        lines.append(h["preview"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


TOOL_REGISTRY["code_semantic_search"] = {
    "name": "code_semantic_search",
    "description": (
        "Find code chunks by *meaning* (vector similarity), not literal text. "
        "Use this when codebase_search misses synonyms or paraphrased intent — "
        "e.g. ask 'where do we rate-limit requests' even if the code says 'throttle'. "
        "Requires the project to have been indexed first via the reindex API."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string", "description": "Project root (used as default project_id)"},
            "project_id": {"type": "string", "description": "Override project_id (defaults to project_dir)"},
            "query": {"type": "string", "description": "Natural-language description of what to find"},
            "top_k": {"type": "integer", "description": "Max hits to return (default 5, max 20)"},
        },
        "required": ["query"],
    },
    "permissions": ["read"],
    "handler": _semantic_search_handler,
}


async def _delegate_handler(params: Dict[str, Any]) -> str:
    """Late-imported to break circular dependency tools → agent_delegate → agent_runtime → tools."""
    from ..agent_delegate import delegate_to_agent
    return await delegate_to_agent(params)


TOOL_REGISTRY["delegate_to_agent"] = {
    "name": "delegate_to_agent",
    "description": (
        "Hand off a focused subtask to a specialist agent (security review, "
        "data analysis, UI design, legal check, DBA opinion, etc.) and return "
        "their answer. Use when a question is OUTSIDE your specialty and would "
        "benefit from a domain expert. Roles: ceo, cto, architect, product, "
        "developer, qa, designer, devops, security, acceptance, data, marketing, "
        "finance, legal."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "Specialist role key, e.g. 'security' or 'designer'"},
            "task": {"type": "string", "description": "Concrete question/subtask (be specific; the specialist won't see your full conversation)"},
            "context": {"type": "object", "description": "Optional key-value context (e.g. file paths, prior findings)"},
            "max_steps": {"type": "integer", "description": "Agent loop budget (default 3, max 8)"},
        },
        "required": ["role", "task"],
    },
    "permissions": ["execute"],
    "handler": _delegate_handler,
}


if _BROWSER_LOADED:
    TOOL_REGISTRY["browser_open"] = {
        "name": "browser_open",
        "description": "Open a URL in a headless browser and return its rendered title + visible text. Use this when web_search results are insufficient or when content is JS-rendered.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL to open"},
                "wait_for": {"type": "string", "description": "Page load condition: 'load' | 'domcontentloaded' | 'networkidle' (default)"},
                "text_limit": {"type": "integer", "description": "Max characters of body text to return (default 8000)"},
            },
            "required": ["url"],
        },
        "permissions": ["network"],
        "handler": browser_open,
    }
    TOOL_REGISTRY["browser_screenshot"] = {
        "name": "browser_screenshot",
        "description": "Take a full-page PNG screenshot of a URL; returns a data: URL (base64). Useful for visual verification.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to capture"},
                "full_page": {"type": "boolean", "description": "Capture full scrollable page (default true)"},
            },
            "required": ["url"],
        },
        "permissions": ["network"],
        "handler": browser_screenshot,
    }
    TOOL_REGISTRY["browser_extract"] = {
        "name": "browser_extract",
        "description": "Open URL and return innerText of every element matching a CSS selector. Best for scraping list pages.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "selector": {"type": "string", "description": "CSS selector e.g. 'article h2.title'"},
                "limit": {"type": "integer", "description": "Max elements to return (default 30)"},
            },
            "required": ["url", "selector"],
        },
        "permissions": ["network"],
        "handler": browser_extract,
    }
    TOOL_REGISTRY["browser_click_flow"] = {
        "name": "browser_click_flow",
        "description": "Open URL, click an element, then return text of the resulting page. Handles SPA route changes / dialogs.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "click_selector": {"type": "string", "description": "CSS selector to click"},
                "extract_selector": {"type": "string", "description": "Optional selector to wait for + extract after click"},
                "text_limit": {"type": "integer", "description": "Max body text chars (default 6000)"},
            },
            "required": ["url", "click_selector"],
        },
        "permissions": ["network"],
        "handler": browser_click_flow,
    }


def _make_git_handler(tool_name: str) -> ToolFunc:
    """Create a registry-compatible handler that wraps execute_git_tool."""
    async def _handler(params: Dict[str, Any]) -> str:
        result = await execute_git_tool(tool_name, params)
        return json.dumps(result, ensure_ascii=False)
    return _handler


_GIT_PERMISSIONS = {
    "git_clone": ["network", "write"],
    "git_status": ["read"],
    "git_checkout": ["write"],
    "git_add": ["write"],
    "git_commit": ["write"],
    "git_push": ["network", "write"],
    "git_diff": ["read"],
    "git_log": ["read"],
    "git_create_pr": ["network", "write"],
    "write_file": ["write"],
}

for _defn in GIT_TOOL_DEFINITIONS:
    TOOL_REGISTRY[_defn["name"]] = {
        "name": _defn["name"],
        "description": _defn["description"],
        "parameters": _defn["parameters"],
        "permissions": _GIT_PERMISSIONS.get(_defn["name"], ["read"]),
        "handler": _make_git_handler(_defn["name"]),
    }


# ─────────────────────────────────────────────────────────────────
# Wave 4: agent message bus tools
#
# Lets agents communicate asynchronously via topics instead of only the
# request/response `delegate_to_agent` tool. Each publish is persisted to
# the `agent_messages` table for replay/audit.
# ─────────────────────────────────────────────────────────────────

async def _agent_publish_handler(params: Dict[str, Any]) -> str:
    from ...database import async_session as AsyncSessionLocal
    from .. import agent_bus

    topic = str(params.get("topic") or "").strip()
    if not topic:
        return "Error: topic is required"
    sender = str(params.get("sender") or "agent")
    task_id = params.get("task_id")
    payload = params.get("payload") or {}
    if not isinstance(payload, dict):
        try:
            import json as _json
            payload = _json.loads(str(payload))
            if not isinstance(payload, dict):
                payload = {"value": payload}
        except Exception:
            payload = {"text": str(payload)}

    async with AsyncSessionLocal() as db:
        try:
            msg = await agent_bus.publish(
                db, topic=topic, sender=sender,
                task_id=str(task_id) if task_id else None,
                payload=payload,
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            return f"Error: publish failed — {e}"
    logger.info(f"[agent_publish] topic={topic} sender={sender} id={msg['id']}")
    return f"Published id={msg['id']} on topic={topic}"


async def _agent_wait_for_handler(params: Dict[str, Any]) -> str:
    from .. import agent_bus
    import json as _json

    topic = str(params.get("topic") or "").strip()
    if not topic:
        return "Error: topic is required"
    timeout = float(params.get("timeout_seconds") or 30.0)
    timeout = max(0.5, min(300.0, timeout))
    task_id = params.get("task_id")
    sender = params.get("sender")

    msg = await agent_bus.wait_for(
        topic=topic, timeout=timeout,
        task_id=str(task_id) if task_id else None,
        sender=str(sender) if sender else None,
    )
    if not msg:
        return f"timeout: no message on topic={topic} within {timeout}s"
    return _json.dumps(msg, ensure_ascii=False, default=str)


TOOL_REGISTRY["agent_publish"] = {
    "name": "agent_publish",
    "description": (
        "Broadcast an async message on the inter-agent bus under a topic. "
        "Other agents (or even other tasks) can subscribe via "
        "`agent_wait_for`. Use this when you want to hand off a piece of "
        "context that downstream agents may or may not consume — without "
        "blocking on a synchronous delegate_to_agent call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic name, e.g. 'spec.v1' or 'task.<id>.review'"},
            "sender": {"type": "string", "description": "Agent identifier (defaults to 'agent')"},
            "task_id": {"type": "string", "description": "Optional pipeline task id to scope the message"},
            "payload": {"type": "object", "description": "JSON dictionary with the message body"},
        },
        "required": ["topic", "payload"],
    },
    "permissions": ["read"],
    "handler": _agent_publish_handler,
}


TOOL_REGISTRY["agent_wait_for"] = {
    "name": "agent_wait_for",
    "description": (
        "Block until another agent publishes a matching message on the "
        "inter-agent bus, or until timeout. Returns the message JSON or a "
        "timeout sentinel. Use sparingly — long timeouts hold the agent "
        "loop. Pair with `agent_publish` from a sibling agent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic to subscribe to (exact match)"},
            "timeout_seconds": {"type": "number", "description": "Max wait, default 30s, max 300s"},
            "task_id": {"type": "string", "description": "Optional task scope filter"},
            "sender": {"type": "string", "description": "Optional sender filter"},
        },
        "required": ["topic"],
    },
    "permissions": ["read"],
    "handler": _agent_wait_for_handler,
}


async def execute_tool(
    tool_name: str,
    params: Dict[str, Any],
    allowed_tools: Optional[List[str]] = None,
) -> str:
    """Execute a tool by name with parameter validation."""
    if allowed_tools is not None and tool_name not in allowed_tools:
        return f"Error: tool '{tool_name}' is not available for this agent"

    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return f"Error: unknown tool '{tool_name}'"

    handler: ToolFunc = tool["handler"]
    try:
        result = await handler(params)
        logger.info(f"Tool {tool_name} executed: {len(result)} chars output")
        return result
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}")
        return f"Error: tool execution failed - {e}"


def get_tool_definitions(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Get OpenAI-compatible tool/function definitions for specified tools."""
    defs = []
    for name, tool in TOOL_REGISTRY.items():
        if tool_names is not None and name not in tool_names:
            continue
        defs.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        })
    return defs
