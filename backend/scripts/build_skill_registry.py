#!/usr/bin/env python3
"""Scan the local filesystem for SKILL.md packs and emit a marketplace
registry JSON that the remote-style loader (``skill_registry.py``) can
serve.

The default `registry.json` shipped with the repo was 8 curated entries
pointing at the same few source files — fine for proving the fetch
pipeline, useless as an actual catalogue. In reality the developer
machine already has dozens of real skills scattered across:

    ~/.agents/skills/**/SKILL.md
    ~/.codex/skills/**/SKILL.md
    ~/.cursor/skills*/**/SKILL.md
    <repo>/skills/{public,custom}/**/SKILL.md
    $EXTRA_SKILL_SOURCE_DIRS  (colon-separated override)

This script walks those roots, parses YAML-ish frontmatter (the same
minimal parser used by ``skill_loader.py``), and produces a JSON file
with one entry per unique slug. ``source_url`` uses ``file://`` so the
installer short-circuits the HTTP fetch and reads straight off disk —
no network, no rate limits, but the full install/upgrade flow still
exercises the same code path (parser, disk copy, DB upsert).

Usage:
    python3 backend/scripts/build_skill_registry.py
    python3 backend/scripts/build_skill_registry.py --out /tmp/reg.json
    EXTRA_SKILL_SOURCE_DIRS=/some/dir:/other \
        python3 backend/scripts/build_skill_registry.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("build_skill_registry")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_yaml_flat(text: str) -> Dict[str, Any]:
    """Parse flat ``key: value`` lines. Matches skill_loader.py exactly."""
    out: Dict[str, Any] = {}
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")
        if value.lower() in ("true", "yes"):
            out[key] = True
        elif value.lower() in ("false", "no"):
            out[key] = False
        elif value.isdigit():
            out[key] = int(value)
        else:
            out[key] = value
    return out


def _slugify(text: str) -> str:
    """Conservative slug: lowercase, ASCII-ish, trim repeated hyphens."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s\u4e00-\u9fa5-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unnamed-skill"


def _first_description_line(body: str, limit: int = 220) -> str:
    """Pull a one-line description from the body when frontmatter omits it."""
    for line in body.splitlines():
        clean = line.strip()
        if not clean or clean.startswith(("#", "```", "---", ">", "|", "-", "*")):
            continue
        return clean[:limit]
    return ""


def _category_from_path(path: Path) -> str:
    """Best-effort category inference from the parent directory name."""
    parents = [p.name.lower() for p in list(path.parents)[:4]]
    keywords = {
        "azure": "cloud",
        "microsoft-foundry": "ai",
        "foundry": "ai",
        "skills-cursor": "productivity",
        "cursor": "productivity",
        "testing": "testing",
        "security": "security",
        "devops": "operations",
        "ops": "operations",
        "design": "design",
        "data": "data",
    }
    for parent in parents:
        for kw, cat in keywords.items():
            if kw in parent:
                return cat
    return "general"


def _parse_skill(path: Path, source_label: str) -> Optional[Dict[str, Any]]:
    """Return a registry entry dict for a given SKILL.md, or None if unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("skip %s: %s", path, exc)
        return None

    match = _FRONTMATTER_RE.match(raw)
    if match:
        meta = _parse_yaml_flat(match.group(1))
        body = match.group(2).strip()
    else:
        # Some SKILL.md files (e.g. Karpathy collection) skip frontmatter
        # entirely. Synthesize metadata from the directory name + body so
        # they still appear in the registry.
        meta = {}
        body = raw.strip()

    name = str(meta.get("name") or path.parent.name).strip()
    slug = _slugify(str(meta.get("slug") or meta.get("name") or path.parent.name))
    description = (
        meta.get("description")
        or _first_description_line(body)
        or ""
    )
    category = (meta.get("category") or _category_from_path(path)).lower()
    tags_raw = meta.get("tags", "")
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []

    return {
        "slug": slug,
        "name": name,
        "description": description,
        "category": category,
        "version": str(meta.get("version") or "1.0.0"),
        "author": str(meta.get("author") or source_label),
        "tags": tags,
        "homepage": str(meta.get("homepage") or ""),
        "license": str(meta.get("license") or ""),
        # file:// → skill_registry.py reads straight off disk without a
        # network round-trip. Keeps installs instant and offline-safe.
        "source_url": path.resolve().as_uri(),
        "_source_label": source_label,
    }


def _scan_root(root: Path, label: str) -> List[Dict[str, Any]]:
    if not root.exists():
        return []
    found: List[Dict[str, Any]] = []
    for md in root.rglob("SKILL.md"):
        entry = _parse_skill(md, label)
        if entry:
            found.append(entry)
    logger.info("scanned %-45s %d skills", f"{label} ({root})", len(found))
    return found


def build_registry(repo_root: Path) -> Dict[str, Any]:
    """Walk every known source root and produce a deduplicated registry dict.

    Priority order matters for slug collisions — the *first* entry wins
    so the repo's own curated skills override anything mirrored from
    external directories.
    """
    home = Path.home()
    sources = [
        (repo_root / "skills" / "public", "agent-hub/public"),
        (repo_root / "skills" / "custom", "agent-hub/custom"),
        (home / ".agents" / "skills", "~/.agents/skills"),
        (home / ".codex" / "skills", "~/.codex/skills"),
        (home / ".cursor" / "skills", "~/.cursor/skills"),
        (home / ".cursor" / "skills-cursor", "~/.cursor/skills-cursor"),
    ]

    for extra in os.environ.get("EXTRA_SKILL_SOURCE_DIRS", "").split(":"):
        extra = extra.strip()
        if extra:
            sources.append((Path(extra).expanduser(), f"env:{extra}"))

    seen: Dict[str, Dict[str, Any]] = {}
    for root, label in sources:
        for entry in _scan_root(root, label):
            slug = entry["slug"]
            if slug in seen:
                continue
            seen[slug] = entry

    # Sort for stable diffs: enabled categories grouped, then alpha by name.
    ordered = sorted(
        seen.values(),
        key=lambda e: (e["category"], e["name"].lower()),
    )

    return {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "description": (
            "Auto-generated from local SKILL.md sources. Re-run "
            "backend/scripts/build_skill_registry.py after adding new "
            "skills to any of the scanned roots."
        ),
        "skills": ordered,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=None,
        help="Output path (default: backend/data/skill_registry.json)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    default_out = repo_root / "backend" / "data" / "skill_registry.json"
    out_path = Path(args.out) if args.out else default_out

    registry = build_registry(repo_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    by_cat: Dict[str, int] = {}
    for s in registry["skills"]:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1

    print(f"\n✓ wrote {out_path.relative_to(repo_root)}")
    print(f"  {len(registry['skills'])} unique skills across {len(by_cat)} categories:")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"    {cat:>14s}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
