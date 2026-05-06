"""File I/O tools — read, write, list, and search files within the sandbox."""
from __future__ import annotations

import os
from typing import Any, Dict

from .sandbox import resolve_safe_path, check_file_size


async def file_read(params: Dict[str, Any]) -> str:
    """Read a file's contents within the sandbox."""
    path = params.get("path", "")
    if not path:
        return "Error: 'path' parameter is required"

    try:
        safe_path = resolve_safe_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.exists(safe_path):
        return f"Error: File not found: {path}"

    try:
        check_file_size(safe_path)
    except ValueError as e:
        return f"Error: {e}"

    try:
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error reading file: {e}"


async def file_write(params: Dict[str, Any]) -> str:
    """Write content to a file within the sandbox."""
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return "Error: 'path' parameter is required"

    try:
        safe_path = resolve_safe_path(path)
    except ValueError as e:
        return f"Error: {e}"

    try:
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def file_list(params: Dict[str, Any]) -> str:
    """List directory contents within the sandbox."""
    path = params.get("path", ".")
    try:
        safe_path = resolve_safe_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isdir(safe_path):
        return f"Error: Not a directory: {path}"

    try:
        entries = sorted(os.listdir(safe_path))
        lines = []
        for entry in entries:
            full = os.path.join(safe_path, entry)
            if os.path.isdir(full):
                lines.append(f"[DIR]  {entry}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"[FILE] {entry} ({size} bytes)")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


async def str_replace(params: Dict[str, Any]) -> str:
    """Replace exact string in a file (deer-flow compatible)."""
    path = params.get("path", "")
    old_string = params.get("old_string", "")
    new_string = params.get("new_string", "")

    if not path or not old_string:
        return "Error: 'path' and 'old_string' are required"

    try:
        safe_path = resolve_safe_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.exists(safe_path):
        return f"Error: File not found: {path}"

    try:
        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read()

        if old_string not in content:
            return f"Error: old_string not found in {path}"

        count = content.count(old_string)
        new_content = content.replace(old_string, new_string, 1)

        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Replaced 1 occurrence in {path} ({count} total matches)"
    except Exception as e:
        return f"Error: {e}"
