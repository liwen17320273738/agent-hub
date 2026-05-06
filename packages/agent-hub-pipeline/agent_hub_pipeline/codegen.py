from __future__ import annotations

import re
from typing import Dict


def extract_code_blocks_from_content(content: str) -> Dict[str, str]:
    """Extract code files from markdown content with `` ` ``language:path blocks.

    Supports:
    - ```dockerfile:deploy/Dockerfile
    - ```language:path and ```:path
    - ```lang\\n// path\\ncontent (CodeGen-style)
    """
    blocks: Dict[str, str] = {}
    for m in re.finditer(r"```\w*:([^\s`\n]+)\n([\s\S]*?)```", content):
        filepath = m.group(1).strip()
        file_content = m.group(2).strip()
        if filepath and file_content:
            blocks[filepath] = file_content
    for m in re.finditer(r"```(\w+)\s*\n//\s*([^\s`\n]+)\n([\s\S]*?)```", content):
        filepath = m.group(2).strip()
        file_content = m.group(3).strip()
        if filepath and file_content and filepath not in blocks:
            blocks[filepath] = file_content
    return blocks
