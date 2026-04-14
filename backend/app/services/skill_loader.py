"""
Skill Loader — discovers and loads SKILL.md files from the filesystem.

Scans `skills/public/` and `skills/custom/` directories for SKILL.md files
with YAML frontmatter, making them available to the skill marketplace
and pipeline stages.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_loaded_skills: Dict[str, Dict[str, Any]] = {}


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """Minimal YAML parser for flat key-value frontmatter (avoids PyYAML dep)."""
    result: Dict[str, Any] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.lower() in ("true", "yes"):
            result[key] = True
        elif value.lower() in ("false", "no"):
            result[key] = False
        elif value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value.strip("'\"")
    return result


def _parse_skill_md(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a SKILL.md file into a skill definition."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return None

    match = _FRONTMATTER_RE.match(content)
    if not match:
        logger.warning(f"No YAML frontmatter in {path}")
        return None

    meta = _parse_yaml_simple(match.group(1))
    body = match.group(2).strip()

    if not meta.get("name"):
        meta["name"] = path.parent.name

    if meta.get("enabled") is False:
        return None

    return {
        "id": meta["name"],
        "name": meta.get("name", path.parent.name),
        "description": meta.get("description", ""),
        "category": meta.get("category", "general"),
        "version": meta.get("version", "1.0.0"),
        "author": meta.get("author", "community"),
        "license": meta.get("license", ""),
        "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()] or [meta["name"]],
        "prompt_body": body,
        "source_path": str(path),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task description or input content"},
                "context": {"type": "string", "description": "Additional context"},
            },
            "required": ["task"],
        },
        "output_schema": {"type": "string"},
        "prompt_template": f"{body}\n\n---\n\n请根据以上指引处理以下任务：\n\n{{task}}\n\n{{context}}",
    }


def discover_skills(skills_root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Scan skills directories and return discovered skill definitions."""
    global _loaded_skills

    if skills_root:
        root = Path(skills_root)
    else:
        root = Path(__file__).resolve().parent.parent.parent.parent / "skills"

    if not root.exists():
        logger.info(f"Skills directory not found: {root}")
        return {}

    skills: Dict[str, Dict[str, Any]] = {}

    for category_dir in ["public", "custom"]:
        cat_path = root / category_dir
        if not cat_path.is_dir():
            continue

        for skill_dir in sorted(cat_path.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            parsed = _parse_skill_md(skill_file)
            if parsed:
                parsed["category"] = category_dir
                skills[parsed["id"]] = parsed
                logger.info(f"Loaded skill: {parsed['id']} from {skill_file}")

    _loaded_skills = skills
    logger.info(f"Discovered {len(skills)} skills from {root}")
    return skills


def get_loaded_skills() -> Dict[str, Dict[str, Any]]:
    """Return currently loaded skills (call discover_skills first)."""
    return _loaded_skills


def get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    """Get a single skill by ID."""
    return _loaded_skills.get(skill_id)


def list_skills_summary() -> List[Dict[str, str]]:
    """Return a compact list of skills for API responses."""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "description": s["description"],
            "category": s["category"],
            "version": s["version"],
        }
        for s in _loaded_skills.values()
    ]
