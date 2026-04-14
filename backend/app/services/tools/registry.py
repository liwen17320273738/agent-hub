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
from .git_tool import (
    git_init, git_status, git_add, git_commit,
    git_diff, git_log, git_branch, git_push,
)
from .build_tool import build_project, install_dependencies, run_tests

logger = logging.getLogger(__name__)

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
    # --- Git tools ---
    "git_init": {
        "name": "git_init",
        "description": "Initialize a new git repository in the project",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
            },
        },
        "permissions": ["write"],
        "handler": git_init,
    },
    "git_status": {
        "name": "git_status",
        "description": "Show current git status (modified/untracked files)",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project directory name"},
            },
        },
        "permissions": ["read"],
        "handler": git_status,
    },
    "git_add": {
        "name": "git_add",
        "description": "Stage files for commit",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "files": {"type": "string", "description": "Files to stage (default: '.' for all)"},
            },
        },
        "permissions": ["write"],
        "handler": git_add,
    },
    "git_commit": {
        "name": "git_commit",
        "description": "Create a git commit with a message",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
        "permissions": ["write"],
        "handler": git_commit,
    },
    "git_diff": {
        "name": "git_diff",
        "description": "Show diff of current changes",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "staged": {"type": "boolean", "description": "Show staged changes only"},
            },
        },
        "permissions": ["read"],
        "handler": git_diff,
    },
    "git_log": {
        "name": "git_log",
        "description": "Show recent commit history",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "count": {"type": "integer", "description": "Number of commits (default: 10)"},
            },
        },
        "permissions": ["read"],
        "handler": git_log,
    },
    "git_branch": {
        "name": "git_branch",
        "description": "Create a new branch or list branches",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "name": {"type": "string", "description": "Branch name to create (omit to list)"},
            },
        },
        "permissions": ["write"],
        "handler": git_branch,
    },
    "git_push": {
        "name": "git_push",
        "description": "Push commits to a remote repository",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "remote": {"type": "string", "description": "Remote name (default: origin)"},
                "branch": {"type": "string", "description": "Branch name (default: main)"},
            },
        },
        "permissions": ["network", "write"],
        "handler": git_push,
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
