"""
Skill Loader — discovers and loads SKILL.md files from the filesystem.

Scans `skills/public/` and `skills/custom/` directories for SKILL.md files
with YAML frontmatter, making them available to the skill marketplace
and pipeline stages.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_loaded_skills: Dict[str, Dict[str, Any]] = {}


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """Minimal YAML parser for flat key-value frontmatter (avoids PyYAML dep).

    Supports scalar values + comma-separated lists for keys ending in
    'tags', 'stages', 'tools', 'criteria'.
    """
    result: Dict[str, Any] = {}
    _LIST_KEYS = {"tags", "trigger_stages", "trigger-stages", "allowed_tools", "allowed-tools",
                  "completion_criteria", "completion-criteria"}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        norm_key = key.replace("-", "_")
        if value.lower() in ("true", "yes"):
            result[norm_key] = True
        elif value.lower() in ("false", "no"):
            result[norm_key] = False
        elif value.isdigit():
            result[norm_key] = int(value)
        elif norm_key in _LIST_KEYS or key in _LIST_KEYS:
            result[norm_key] = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
        else:
            result[norm_key] = value.strip("'\"")
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
        "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [t.strip() for t in str(meta.get("tags", "")).split(",") if t.strip()] or [meta["name"]],
        "trigger_stages": meta.get("trigger_stages", []),
        "completion_criteria": meta.get("completion_criteria", []),
        "allowed_tools": meta.get("allowed_tools", []),
        "execution_mode": meta.get("execution_mode", "inline"),
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


def _scan_skill_dirs(root: Path, skills: Dict[str, Dict[str, Any]], source_type: str = "public") -> int:
    """Scan a directory of skill folders (each containing SKILL.md) and add to skills dict."""
    count = 0
    if not root.is_dir():
        return 0
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        parsed = _parse_skill_md(skill_file)
        if parsed and parsed["id"] not in skills:
            parsed["source_type"] = source_type
            skills[parsed["id"]] = parsed
            logger.info(f"Loaded skill: {parsed['id']} from {skill_file}")
            count += 1
    return count


def discover_skills(skills_root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Scan skills directories and return discovered skill definitions.

    Scans:
    1. {skills_root}/public/ and {skills_root}/custom/ (including symlinks)
    2. EXTRA_SKILLS_DIRS env var — comma-separated list of additional directories
       Each entry should point to a directory containing skill subdirs with SKILL.md
    """
    global _loaded_skills

    if skills_root:
        root = Path(skills_root)
    else:
        candidates = [
            Path(__file__).resolve().parent.parent.parent.parent / "skills",
            Path("/app/skills"),  # Docker container path
        ]
        root = next((p for p in candidates if p.exists()), candidates[0])

    skills: Dict[str, Dict[str, Any]] = {}

    if root.exists():
        for category_dir in ["public", "custom"]:
            _scan_skill_dirs(root / category_dir, skills, source_type=category_dir)

    extra_dirs = os.environ.get("EXTRA_SKILLS_DIRS", "")
    for extra in extra_dirs.split(","):
        extra = extra.strip()
        if extra:
            extra_path = Path(extra)
            added = _scan_skill_dirs(extra_path, skills, source_type="external")
            if added:
                logger.info(f"Loaded {added} external skills from {extra_path}")

    _loaded_skills = skills
    logger.info(f"Discovered {len(skills)} skills total")
    return skills


async def sync_skills_to_db(db) -> int:
    """Sync filesystem SKILL.md definitions into the Skill DB table.

    Uses the rich prompt_body from the markdown files, preserving
    frontmatter category for STAGE_SKILL_MAP matching.
    Returns the number of skills synced.
    """
    from ..models.skill import Skill

    if not _loaded_skills:
        discover_skills()

    synced = 0
    for skill_id, fs_skill in _loaded_skills.items():
        existing = await db.get(Skill, skill_id)
        if existing:
            if not existing.prompt_template or len(existing.prompt_template) < 100:
                existing.prompt_template = fs_skill.get("prompt_template", existing.prompt_template)
            if existing.category in ("public", "custom"):
                existing.category = fs_skill.get("category", existing.category)
            continue

        skill = Skill(
            id=skill_id,
            name=fs_skill.get("name", skill_id),
            category=fs_skill.get("category", "general"),
            description=fs_skill.get("description", ""),
            version=fs_skill.get("version", "1.0.0"),
            author=fs_skill.get("author", "community"),
            prompt_template=fs_skill.get("prompt_template", ""),
            input_schema=fs_skill.get("input_schema", {}),
            output_schema=fs_skill.get("output_schema", {}),
            tags=fs_skill.get("tags", []),
            is_builtin=True,
            enabled=True,
        )
        db.add(skill)
        synced += 1
        logger.info(f"[sync] Synced filesystem skill to DB: {skill_id}")

    if synced:
        await db.flush()
    return synced


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
