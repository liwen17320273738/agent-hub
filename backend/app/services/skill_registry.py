"""Remote-first skill marketplace service.

Unlike `skill_marketplace.py` — whose registry is hardcoded Python dicts —
this module pulls a JSON registry from either a local file or an HTTP(S)
URL, fetches the underlying SKILL.md on demand, and installs it to
`skills/custom/<slug>/SKILL.md` + upserts the DB row.

Design goals:
- **Zero schema lock-in on the remote side.** We only require `slug` +
  `source_url` on each entry; everything else is metadata surfaced to
  the UI. Missing fields default to safe values.
- **Never trust the remote blindly.** SKILL.md payloads are size-capped
  (256KB) and timeout-bounded, and install always goes through
  `skill_loader._parse_skill_md` so frontmatter parsing is uniform with
  the local pipeline.
- **Cheap cache, explicit bust.** In-memory TTL (5 min) so the UI can
  poll `/listings` without pummeling GitHub; `/refresh` zeroes the
  cache for ops.

Kept separate from the legacy `skill_marketplace.py` so neither file
becomes a dumping ground — the latter still backs the in-code
`MARKETPLACE_REGISTRY` that pipeline stages execute against.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.skill import Skill
from .skill_loader import _parse_skill_md  # noqa: intentionally reusing the loader

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "skill_registry.json"
)
GITHUB_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "github_skill_registry.json"
)
# The crawler writes auto-discovered / untrusted entries here; the
# review pipeline endpoints in ``api/pipeline.py`` read & mutate this
# file. Deliberately NOT included in ``_registry_sources`` so pending
# entries never leak into the public market listing.
GITHUB_PENDING_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "github_pending_registry.json"
)
REGISTRY_CACHE_TTL_SEC = 300
FETCH_TIMEOUT_SEC = 15
MAX_SKILL_MD_BYTES = 256 * 1024  # 256KB


# ── In-memory registry cache ─────────────────────────────────────────
# Keyed by sources tuple so swapping env vars at runtime doesn't return
# stale results from the previous configuration.
_registry_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def _registry_sources() -> List[str]:
    """Return the ordered list of registry sources to merge.

    Priority rules (same slug = first source wins):
    1. ``SKILL_REGISTRY_URLS`` (comma-separated, full override)
    2. ``SKILL_REGISTRY_URL`` (single override, legacy)
    3. Default: local scan + optional GitHub crawl (merged)

    Splitting into two env names keeps the legacy one working while
    still letting ops enable multi-source mode with one config line.
    """
    urls_env = os.environ.get("SKILL_REGISTRY_URLS", "").strip()
    if urls_env:
        return [u.strip() for u in urls_env.split(",") if u.strip()]

    single = os.environ.get("SKILL_REGISTRY_URL", "").strip()
    if single:
        return [single]

    sources: List[str] = [str(DEFAULT_REGISTRY_PATH)]
    if GITHUB_REGISTRY_PATH.exists():
        sources.append(str(GITHUB_REGISTRY_PATH))
    return sources


def _cache_key(sources: List[str]) -> str:
    return "|".join(sources)


async def _fetch_one(source: str) -> List[Dict[str, Any]]:
    """Load raw entries from a single source (file path or HTTP URL)."""
    raw: str
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SEC) as client:
            resp = await client.get(source)
            resp.raise_for_status()
            raw = resp.text
    else:
        path = Path(source)
        if not path.exists():
            logger.warning("skill registry not found at %s", path)
            return []
        raw = path.read_text(encoding="utf-8")

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("skill registry JSON parse error for %s: %s", source, e)
        return []

    return doc.get("skills") or []


async def _load_registry(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch + normalize registry entries from every configured source.

    Cached for ``REGISTRY_CACHE_TTL_SEC``. Multiple sources are merged
    with first-source-wins dedup so your curated local list always
    overrides whatever the GitHub crawl happens to surface.
    """
    sources = _registry_sources()
    key = _cache_key(sources)

    if not force:
        hit = _registry_cache.get(key)
        if hit and (time.time() - hit[0]) < REGISTRY_CACHE_TTL_SEC:
            return hit[1]

    seen_slugs: set = set()
    normalized: List[Dict[str, Any]] = []

    for source in sources:
        try:
            entries = await _fetch_one(source)
        except Exception as e:
            logger.warning("registry source %s failed: %s", source, e)
            continue

        added = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            source_url = str(entry.get("source_url") or "").strip()
            if not slug or not source_url:
                continue
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            normalized.append(
                {
                    "slug": slug,
                    "name": entry.get("name") or slug,
                    "description": entry.get("description") or "",
                    "category": (entry.get("category") or "general").lower(),
                    "version": entry.get("version") or "1.0.0",
                    "author": entry.get("author") or "community",
                    "tags": entry.get("tags") or [],
                    "homepage": entry.get("homepage") or "",
                    "license": entry.get("license") or "",
                    "source_url": source_url,
                    # Provenance (set by the GitHub crawler; absent for
                    # the local-scan source). Frontend uses these to
                    # render a "@owner/repo ★ 12k" badge on the card.
                    "source_repo": entry.get("source_repo") or "",
                    "source_stars": int(entry.get("source_stars") or 0),
                }
            )
            added += 1
        logger.info("loaded %d skills from %s", added, source)

    _registry_cache[key] = (time.time(), normalized)
    return normalized


def refresh_registry_cache() -> None:
    """Drop all cached registry data; next listing call re-fetches."""
    _registry_cache.clear()


# ── Listings: merge registry with local install state ───────────────
_VERSION_SPLIT = re.compile(r"[.\-+]")


def _version_tuple(v: str) -> Tuple[int, ...]:
    """Parse a SemVer-ish string into a comparable tuple.

    Falls back to (0,) for garbage input — the UI won't offer an upgrade
    if we can't compare versions cleanly, which is the right default.
    """
    parts: List[int] = []
    for chunk in _VERSION_SPLIT.split(v or ""):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            break
    return tuple(parts) or (0,)


async def list_marketplace(db: AsyncSession) -> List[Dict[str, Any]]:
    """Return registry entries enriched with each skill's install state.

    Install state is one of ``not_installed`` / ``installed`` /
    ``outdated`` — the UI maps these to "安装 / 已安装 / 有更新".
    """
    entries = await _load_registry()
    if not entries:
        return []

    slugs = [e["slug"] for e in entries]
    result = await db.execute(select(Skill).where(Skill.id.in_(slugs)))
    local_by_id = {s.id: s for s in result.scalars().all()}

    listings: List[Dict[str, Any]] = []
    for e in entries:
        local = local_by_id.get(e["slug"])
        if local is None:
            state = "not_installed"
            local_version = None
        else:
            lv = _version_tuple(local.version)
            rv = _version_tuple(e["version"])
            state = "outdated" if lv < rv else "installed"
            local_version = local.version
        listings.append(
            {
                **e,
                "install_state": state,
                "local_version": local_version,
                "enabled": bool(local and local.enabled),
            }
        )
    return listings


# ── Install / upgrade from remote ───────────────────────────────────
async def _fetch_skill_md(source_url: str) -> str:
    """Download a SKILL.md payload with strict size / timeout limits."""
    if source_url.startswith("file://"):
        path = Path(source_url[7:])
        if not path.exists():
            raise FileNotFoundError(f"SKILL.md not found: {path}")
        return path.read_text(encoding="utf-8")

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SEC, follow_redirects=True) as client:
        # Stream + hard-cap: a hostile registry could otherwise point at a
        # 10GB file and blow up our worker RAM.
        async with client.stream("GET", source_url) as resp:
            resp.raise_for_status()
            chunks: List[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_SKILL_MD_BYTES:
                    raise ValueError(
                        f"SKILL.md exceeds size limit ({total} > {MAX_SKILL_MD_BYTES} bytes)"
                    )
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")


def _resolve_skills_root() -> Path:
    """Mirror skill_loader's lookup so installs land in the same dir it scans."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "skills",
        Path("/app/skills"),  # Docker
    ]
    for p in candidates:
        if p.exists():
            return p
    # Create the first candidate if nothing exists yet (fresh install).
    root = candidates[0]
    root.mkdir(parents=True, exist_ok=True)
    return root


async def install_from_registry(
    db: AsyncSession, slug: str, actor: str = "community"
) -> Dict[str, Any]:
    """Install (or upgrade) a skill from the remote registry.

    Returns a dict describing the installed Skill row and a human-readable
    ``action`` field of ``installed`` / ``upgraded`` / ``reinstalled``.
    """
    entries = await _load_registry()
    entry = next((e for e in entries if e["slug"] == slug), None)
    if not entry:
        raise KeyError(f"slug not in registry: {slug}")

    md_text = await _fetch_skill_md(entry["source_url"])

    # Persist to disk so the local loader + hot-reload see it, then
    # delegate parsing to the SAME path that existing public/custom
    # skills go through — this is what guarantees uniform behaviour.
    skills_root = _resolve_skills_root()
    skill_dir = skills_root / "custom" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(md_text, encoding="utf-8")

    parsed = _parse_skill_md(skill_md)
    if not parsed:
        raise ValueError(
            f"downloaded SKILL.md for {slug} has no valid YAML frontmatter"
        )

    # Prefer registry metadata (curated) over frontmatter for display fields
    # users actually see in the marketplace, but KEEP the prompt_template
    # the loader produced from the body — that's the actual skill payload.
    existing = await db.get(Skill, slug)
    action: str
    if existing:
        prev_version = existing.version
        existing.name = entry["name"] or existing.name
        existing.description = entry["description"] or existing.description
        existing.category = entry["category"] or existing.category
        existing.version = entry["version"] or existing.version
        existing.author = entry["author"] or existing.author
        existing.tags = entry["tags"] or existing.tags
        existing.prompt_template = parsed["prompt_template"]
        existing.is_builtin = False  # installed from marketplace = custom
        if _version_tuple(prev_version) < _version_tuple(entry["version"]):
            action = "upgraded"
        else:
            action = "reinstalled"
        skill = existing
    else:
        skill = Skill(
            id=slug,
            name=entry["name"],
            description=entry["description"],
            category=entry["category"],
            version=entry["version"],
            author=entry["author"],
            tags=entry["tags"],
            prompt_template=parsed["prompt_template"],
            input_schema=parsed.get("input_schema") or {},
            output_schema=parsed.get("output_schema") or {},
            enabled=True,
            is_builtin=False,
        )
        db.add(skill)
        action = "installed"

    await db.flush()

    logger.info(
        "[marketplace] %s %s → v%s by %s (%d bytes)",
        action, slug, entry["version"], actor, len(md_text),
    )

    return {
        "ok": True,
        "action": action,
        "skill": {
            "id": skill.id,
            "name": skill.name,
            "version": skill.version,
            "category": skill.category,
            "enabled": skill.enabled,
        },
    }
