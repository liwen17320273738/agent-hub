"""
Sandbox — path validation and resource constraints for tool execution.

All file/bash tools must go through sandbox validation to ensure:
1. Paths stay within allowed directories
2. Symlinks don't escape the sandbox
3. File size limits are enforced
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

_DEFAULT_SANDBOX_ROOT = "/tmp/agent-hub-sandbox"
_sandbox_root: Optional[str] = None
_max_file_size: int = 10 * 1024 * 1024  # 10 MB


def configure_sandbox(
    root: Optional[str] = None,
    allowed_dirs: Optional[List[str]] = None,
    max_file_size: int = 10 * 1024 * 1024,
) -> str:
    """Set up the sandbox root directory. Returns the resolved path."""
    global _sandbox_root, _max_file_size
    _sandbox_root = root or _DEFAULT_SANDBOX_ROOT
    _max_file_size = max_file_size

    os.makedirs(_sandbox_root, exist_ok=True)
    return _sandbox_root


def get_sandbox_root() -> str:
    global _sandbox_root
    if _sandbox_root is None:
        configure_sandbox()
    return _sandbox_root  # type: ignore[return-value]


def resolve_safe_path(path: str) -> str:
    """Resolve a path relative to sandbox root, preventing escape.

    Raises ValueError if the resolved path is outside the sandbox.
    """
    root = Path(get_sandbox_root()).resolve()
    if os.path.isabs(path):
        resolved = Path(path).resolve()
    else:
        resolved = (root / path).resolve()

    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"Path traversal denied: {path} resolves outside sandbox")

    return str(resolved)


def check_file_size(path: str) -> None:
    """Raise ValueError if file exceeds size limit."""
    if os.path.exists(path):
        size = os.path.getsize(path)
        if size > _max_file_size:
            raise ValueError(
                f"File too large: {size} bytes (limit: {_max_file_size} bytes)"
            )
