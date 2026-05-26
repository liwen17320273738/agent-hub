"""
Pen (.pen) Design Token Generator
==================================

Generates Pencil-compatible .pen files from design specifications.

.pen files follow Pencil's schema — they represent design system tokens,
component definitions, and screen layouts that can be opened and edited
in the Pencil editor.

The pipeline calls ``generate_pen_file()`` during the Layer 9.5 visual
generation phase for the ``design`` stage, producing a .pen artifact
alongside the PNG mockup and HTML prototype.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PEN_DIR = "pen_designs"

# Pencil-compatible node type constants
# These correspond to the Pencil schema primitives
NODE_FRAME = "frame"
NODE_TEXT = "text"
NODE_REF = "ref"


def _slugify_filename(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]", "-", (text or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len] or "design")


def _extract_color_tokens(design_spec: str) -> Dict[str, str]:
    """Extract color design tokens from a design spec."""
    tokens: Dict[str, str] = {}
    color_patterns = [
        (r"主色[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "primary"),
        (r"辅色[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "secondary"),
        (r"背景色[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "background"),
        (r"文字色[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "text"),
        (r"强调色[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "accent"),
        (r"primary[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "primary"),
        (r"accent[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "accent"),
        (r"background[：:]\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsl?\([^)]+\))", "background"),
    ]
    for pattern, token_name in color_patterns:
        match = re.search(pattern, design_spec, re.IGNORECASE)
        if match:
            tokens[f"color-{token_name}"] = match.group(1)
    return tokens


def _extract_font_tokens(design_spec: str) -> Dict[str, str]:
    """Extract typography design tokens from a design spec."""
    tokens: Dict[str, str] = {}
    patterns = [
        (r"字体[：:]\s*(.+?)(?:[。\n]|$)", "font-family"),
        (r"font-family[：:]\s*(.+?)(?:[;\n]|$)", "font-family"),
        (r"正文字号[：:]\s*(\d+)", "font-size-body"),
        (r"标题字号[：:]\s*(\d+)", "font-size-heading"),
        (r"正文[字号大小][：:]\s*(\d+)", "font-size-body"),
        (r"标题[字号大小][：:]\s*(\d+)", "font-size-heading"),
    ]
    for pattern, token_name in patterns:
        match = re.search(pattern, design_spec, re.IGNORECASE)
        if match:
            tokens[token_name] = match.group(1).strip()
    return tokens


def _extract_spacing_tokens(design_spec: str) -> Dict[str, str]:
    """Extract spacing/layout tokens."""
    tokens: Dict[str, str] = {}
    patterns = [
        (r"间距[：:]\s*(\d+)", "spacing"),
        (r"[圆角][：:]\s*(\d+)", "border-radius"),
    ]
    for pattern, token_name in patterns:
        match = re.search(pattern, design_spec, re.IGNORECASE)
        if match:
            tokens[token_name] = match.group(1).strip()
    return tokens


def _build_pen_document(
    project_name: str,
    design_tokens: Dict[str, str],
    design_spec: str,
) -> Dict[str, Any]:
    """Build a .pen document structure from design tokens and spec.

    Returns a dict that can be written as a .pen file (JSON format
    compatible with the Pencil editor schema). Has three sections:
    1. Variables — design tokens (colors, typography, spacing)
    2. Artboard — a frame representing the main screen
    3. Component palette — reusable UI primitives
    """
    # Build Pencil variables from design tokens
    variables: List[Dict[str, Any]] = []

    # Color variables
    color_fills = []
    for token_key, value in design_tokens.items():
        if token_key.startswith("color-"):
            name = token_key.replace("color-", "颜色/")
            variables.append({
                "name": name,
                "type": "color",
                "value": value,
            })
            color_fills.append(value)

    # Font variables
    font_family = design_tokens.get("font-family", "Inter, sans-serif")
    body_size = design_tokens.get("font-size-body", "16")
    heading_size = design_tokens.get("font-size-heading", "24")
    variables.extend([
        {"name": "字体/正文字号", "type": "number", "value": body_size},
        {"name": "字体/标题字号", "type": "number", "value": heading_size},
        {"name": "字体/字体族", "type": "string", "value": font_family},
    ])

    # Spacing variables
    spacing = design_tokens.get("spacing", "16")
    radius = design_tokens.get("border-radius", "8")
    variables.extend([
        {"name": "布局/间距", "type": "number", "value": spacing},
        {"name": "布局/圆角", "type": "number", "value": radius},
    ])

    # Default color if none found
    primary_color = color_fills[0] if color_fills else "#4F46E5"

    # Build artboard (main screen frame)
    # Pencil schema: a frame with children
    artboard = {
        "id": "main-screen",
        "type": "frame",
        "name": f"{project_name} - 主界面",
        "reusable": False,
        "width": 1440,
        "height": 900,
        "fill": design_tokens.get("color-background", "#FFFFFF"),
        "layout": "vertical",
        "padding": int(spacing),
        "gap": int(spacing),
        "children": [
            {
                "id": "header-area",
                "type": "frame",
                "name": "顶部导航栏",
                "width": "fill_container",
                "height": 64,
                "fill": primary_color,
                "layout": "horizontal",
                "padding": 16,
                "gap": 8,
                "children": [
                    {
                        "id": "logo-text",
                        "type": "text",
                        "content": project_name,
                        "fontSize": int(heading_size) if heading_size.isdigit() else 20,
                        "fill": "#FFFFFF",
                        "fontWeight": 600,
                    },
                ],
            },
            {
                "id": "content-area",
                "type": "frame",
                "name": "内容区域",
                "width": "fill_container",
                "height": "fill_container",
                "fill": "#F5F5F5",
                "layout": "horizontal",
                "gap": int(spacing),
                "padding": int(spacing),
                "children": [
                    {
                        "id": "sidebar",
                        "type": "frame",
                        "name": "侧边栏",
                        "width": 240,
                        "height": "fill_container",
                        "fill": "#FFFFFF",
                        "layout": "vertical",
                        "padding": 16,
                        "gap": 8,
                    },
                    {
                        "id": "main-content",
                        "type": "frame",
                        "name": "主要内容区",
                        "width": "fill_container",
                        "height": "fill_container",
                        "fill": "#FFFFFF",
                        "layout": "vertical",
                        "padding": int(spacing),
                        "gap": int(spacing),
                    },
                ],
            },
            {
                "id": "footer-area",
                "type": "frame",
                "name": "页脚",
                "width": "fill_container",
                "height": 48,
                "fill": "#E5E5E5",
                "layout": "horizontal",
            },
        ],
    }

    return {
        "version": "1.0",
        "created_at": datetime.utcnow().isoformat(),
        "project": project_name,
        "variables": variables,
        "nodes": [artboard],
    }


def generate_pen_file(
    task_id: str,
    task_worktree: str,
    design_spec: str,
    project_name: str = "",
    design_tokens: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Generate a .pen design file from the design specification.

    Args:
        task_id: Pipeline task ID
        task_worktree: Working directory for this task
        design_spec: The raw design stage output text
        project_name: Human-friendly project name
        design_tokens: Pre-extracted design tokens (optional)

    Returns:
        Dict with ``penPath`` and ``ok`` status, or None on failure.
    """
    try:
        if not task_worktree:
            logger.warning("[pen] No task_worktree — skipping .pen generation")
            return None

        pen_dir = os.path.join(task_worktree, PEN_DIR)
        os.makedirs(pen_dir, exist_ok=True)

        filename = f"{_slugify_filename(project_name or task_id, max_len=32)}.pen"
        pen_path = os.path.join(pen_dir, filename)

        # Extract tokens
        extracted_tokens: Dict[str, str] = {}
        if design_tokens:
            # Convert design_tokens dict to flat string-keyed format
            for section in ("colors", "typography", "spacing"):
                if isinstance(design_tokens.get(section), dict):
                    for k, v in design_tokens[section].items():
                        extracted_tokens[f"{section}-{k}"] = str(v)
        extracted_tokens.update(_extract_color_tokens(design_spec))
        extracted_tokens.update(_extract_font_tokens(design_spec))
        extracted_tokens.update(_extract_spacing_tokens(design_spec))

        doc = _build_pen_document(
            project_name=project_name or task_id,
            design_tokens=extracted_tokens,
            design_spec=design_spec,
        )

        with open(pen_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        rel_path = f"{PEN_DIR}/{filename}"

        logger.info("[pen] Generated .pen file: %s", pen_path)

        return {
            "ok": True,
            "penPath": pen_path,
            "relativePath": rel_path,
        }

    except Exception as e:
        logger.warning("[pen] Failed to generate .pen file: %s", e)
        return {
            "ok": False,
            "error": str(e),
        }


def check_pen_resources() -> bool:
    """Check if .pen file generation is possible (always true — pure Python).

    Returns:
        True always, since .pen generation is pure Python (no external
        dependencies). The generated .pen files can be opened in the
        Pencil editor when the user opens the task worktree.
    """
    return True
