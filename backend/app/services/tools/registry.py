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
