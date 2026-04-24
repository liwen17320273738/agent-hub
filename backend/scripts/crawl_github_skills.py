#!/usr/bin/env python3
"""Crawl public GitHub repos for SKILL.md files and emit a marketplace
registry JSON.

Companion to ``build_skill_registry.py``:
- ``build_skill_registry.py`` scans the **local filesystem** (your home
  dir + repo) and is fast / offline / deterministic.
- ``crawl_github_skills.py`` (this script) scans **remote GitHub repos**
  so the marketplace can surface skills that were never installed on
  the machine running agent-hub.

The output schema is identical (``skills: [...]`` with ``slug``,
``source_url``, etc.), so the same ``skill_registry.py`` service can
consume either file. You can also merge them, see
``backend/data/README.md``.

Key design decisions:
- **Seed-list driven, not full-text search.** GitHub code search requires
  auth and the results are noisy; curated repos give us higher quality
  with zero API keys needed.
- **One HTTP GET per repo tree.** We ask for the full recursive tree and
  filter for SKILL.md client-side — that's cheap even for large repos.
- **Rate-limit aware.** Unauthenticated: 60 req/h. Set ``GITHUB_TOKEN``
  (classic PAT, no scope needed for public repos) to get 5,000 req/h.
- **Hostile-repo safe.** Per-repo skill cap (default 100), per-file size
  cap (256KB), archived-repo skip. A single evil repo can't poison the
  whole registry.

Usage:
    python3 backend/scripts/crawl_github_skills.py
    GITHUB_TOKEN=ghp_xxx python3 backend/scripts/crawl_github_skills.py
    python3 backend/scripts/crawl_github_skills.py --sources /tmp/my.json --out /tmp/reg.json
    GITHUB_SKILL_SOURCES=anthropics/skills,me/my-skills \
        python3 backend/scripts/crawl_github_skills.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import httpx
except ImportError:
    print("httpx is required (pip install httpx)", file=sys.stderr)
    sys.exit(2)

logger = logging.getLogger("crawl_github_skills")

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

MAX_SKILL_MD_BYTES = 256 * 1024
DEFAULT_PER_REPO_CAP = 100
REQ_TIMEOUT_SEC = 30


# ── YAML parsing: same flat parser we use everywhere else ───────────
def _parse_yaml_flat(text: str) -> Dict[str, Any]:
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
    s = text.lower().strip()
    s = re.sub(r"[^\w\s\u4e00-\u9fa5-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unnamed-skill"


def _first_description_line(body: str, limit: int = 220) -> str:
    for line in body.splitlines():
        clean = line.strip()
        if not clean or clean.startswith(("#", "```", "---", ">", "|")):
            continue
        return clean[:limit]
    return ""


# ── HTTP plumbing ──────────────────────────────────────────────────
class GithubClient:
    """Tiny GitHub REST wrapper with token auth + rate-limit-aware sleep."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-hub-skill-crawler/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            logger.info("using GITHUB_TOKEN (auth: 5000 req/h)")
        else:
            logger.info("no GITHUB_TOKEN set (anon: 60 req/h)")
        self.client = httpx.Client(timeout=REQ_TIMEOUT_SEC, headers=headers)

    def get(self, url: str) -> Optional[httpx.Response]:
        """GET with one-shot retry on 403 rate-limit (respects reset header)."""
        for attempt in (1, 2):
            resp = self.client.get(url)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                now = int(time.time())
                wait = max(5, reset - now + 2) if reset > now else 60
                if attempt == 1 and wait < 120:
                    logger.warning("rate-limited, sleeping %ds then retrying", wait)
                    time.sleep(wait)
                    continue
                logger.error("rate-limited; reset in %ds (aborting %s)", wait, url)
                return None
            return resp
        return None

    def close(self) -> None:
        self.client.close()


# ── Repo metadata + tree walking ────────────────────────────────────
def _fetch_repo_meta(gh: GithubClient, owner: str, repo: str) -> Optional[Dict[str, Any]]:
    """Return stars / license / archived flag for a repo, or None if missing."""
    resp = gh.get(f"{GITHUB_API}/repos/{owner}/{repo}")
    if not resp or resp.status_code != 200:
        logger.warning("repo meta unavailable %s/%s: %s",
                       owner, repo, resp.status_code if resp else "n/a")
        return None
    return resp.json()


def _fetch_tree(
    gh: GithubClient, owner: str, repo: str, branch: str,
) -> List[Dict[str, Any]]:
    """Return the full recursive tree for a branch. Empty list on error."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = gh.get(url)
    if not resp:
        return []
    if resp.status_code != 200:
        logger.warning("tree fetch failed %s/%s@%s: %s %s",
                       owner, repo, branch, resp.status_code, resp.text[:160])
        return []
    data = resp.json()
    if data.get("truncated"):
        # > 100k files; we'll still process whatever came back.
        logger.warning("tree truncated for %s/%s (repo too large)", owner, repo)
    return data.get("tree") or []


def _filter_skill_paths(
    tree: List[Dict[str, Any]],
    path_prefix: str = "",
    per_repo_cap: int = DEFAULT_PER_REPO_CAP,
) -> List[Dict[str, Any]]:
    """Pick blob entries whose path ends in SKILL.md and match path_prefix."""
    out: List[Dict[str, Any]] = []
    prefix = path_prefix.lstrip("/")
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path") or ""
        if not path.endswith("SKILL.md"):
            continue
        if prefix and not path.startswith(prefix):
            continue
        if entry.get("size", 0) > MAX_SKILL_MD_BYTES:
            logger.info("skipping oversize SKILL.md %s (%d bytes)", path, entry.get("size"))
            continue
        out.append(entry)
        if len(out) >= per_repo_cap:
            logger.warning("hit per-repo cap (%d) — truncating", per_repo_cap)
            break
    return out


def _fetch_raw(
    gh: GithubClient, owner: str, repo: str, branch: str, path: str,
) -> Optional[str]:
    """Download a file via raw.githubusercontent.com (no API quota cost)."""
    url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
    try:
        resp = gh.client.get(url)  # bypass the rate-aware .get(); raw != api
    except httpx.HTTPError as e:
        logger.warning("raw fetch error %s: %s", url, e)
        return None
    if resp.status_code != 200:
        logger.warning("raw fetch %s returned %s", url, resp.status_code)
        return None
    return resp.text


# ── Parsing a single SKILL.md into a registry entry ──────────────────
def _build_entry(
    *,
    owner: str,
    repo: str,
    branch: str,
    path: str,
    raw_md: str,
    repo_meta: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    match = _FRONTMATTER_RE.match(raw_md)
    if match:
        meta = _parse_yaml_flat(match.group(1))
        body = match.group(2).strip()
    else:
        meta = {}
        body = raw_md.strip()

    # Many Anthropic skills intentionally omit `name` (uses dir name).
    dir_name = Path(path).parent.name or "root"
    name = str(meta.get("name") or dir_name).strip()

    # slug dedup: prefer the repo path so two different repos' "my-skill"
    # don't collide silently. Format: owner-repo-dirname.
    slug_base = meta.get("slug") or meta.get("name") or dir_name
    slug = _slugify(f"{owner}-{repo}-{slug_base}")

    description = (
        meta.get("description")
        or _first_description_line(body)
        or repo_meta.get("description")
        or ""
    )

    tags_raw = meta.get("tags", "")
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []
    # Always add a provenance tag so the UI can filter by source.
    provenance_tag = f"src:{owner}/{repo}"
    if provenance_tag not in tags:
        tags.append(provenance_tag)

    license_name = ""
    if isinstance(repo_meta.get("license"), dict):
        license_name = repo_meta["license"].get("spdx_id") or repo_meta["license"].get("name") or ""
    license_name = str(meta.get("license") or license_name)

    return {
        "slug": slug,
        "name": name,
        "description": description,
        "category": str(meta.get("category") or "community").lower(),
        "version": str(meta.get("version") or "1.0.0"),
        "author": str(meta.get("author") or owner),
        "tags": tags,
        "homepage": f"https://github.com/{owner}/{repo}/blob/{branch}/{path}",
        "license": license_name,
        # Raw URL — skill_registry.install_from_registry downloads this
        # at install time, same as any other HTTP entry.
        "source_url": f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}",
        "source_repo": f"{owner}/{repo}",
        "source_stars": int(repo_meta.get("stargazers_count") or 0),
    }


# ── Orchestration ───────────────────────────────────────────────────
def _load_sources(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        logger.error("sources file missing: %s", path)
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("sources JSON parse error: %s", e)
        return []
    repos = doc.get("repos") or []

    # Allow quick ad-hoc additions via env (comma-separated owner/repo list).
    env_extra = os.environ.get("GITHUB_SKILL_SOURCES", "").strip()
    if env_extra:
        for slug in env_extra.split(","):
            slug = slug.strip()
            if "/" not in slug:
                continue
            owner, _, repo = slug.partition("/")
            repos.append({"owner": owner, "repo": repo, "branch": "main", "path_prefix": ""})

    return repos


def crawl(
    sources: Iterable[Dict[str, Any]],
    per_repo_cap: int = DEFAULT_PER_REPO_CAP,
) -> List[Dict[str, Any]]:
    gh = GithubClient()
    entries: List[Dict[str, Any]] = []
    seen_slugs: set = set()

    try:
        for src in sources:
            owner = src.get("owner")
            repo = src.get("repo")
            branch = src.get("branch") or "main"
            path_prefix = src.get("path_prefix") or ""
            if not owner or not repo:
                logger.warning("skipping malformed source entry: %r", src)
                continue

            logger.info("── %s/%s@%s (prefix=%r) ──", owner, repo, branch, path_prefix)
            meta = _fetch_repo_meta(gh, owner, repo)
            if meta is None:
                continue
            if meta.get("archived"):
                logger.info("skip archived repo %s/%s", owner, repo)
                continue

            # Prefer the branch the repo declares as default when the
            # requested one 404s — saves an entry for half-broken sources.
            tree = _fetch_tree(gh, owner, repo, branch)
            if not tree and meta.get("default_branch") and meta["default_branch"] != branch:
                branch = meta["default_branch"]
                logger.info("fallback to default branch %s", branch)
                tree = _fetch_tree(gh, owner, repo, branch)

            skill_files = _filter_skill_paths(tree, path_prefix, per_repo_cap)
            logger.info("  found %d SKILL.md files", len(skill_files))

            for f in skill_files:
                path = f["path"]
                raw = _fetch_raw(gh, owner, repo, branch, path)
                if not raw:
                    continue
                entry = _build_entry(
                    owner=owner, repo=repo, branch=branch, path=path,
                    raw_md=raw, repo_meta=meta,
                )
                if not entry:
                    continue
                if entry["slug"] in seen_slugs:
                    continue
                seen_slugs.add(entry["slug"])
                entries.append(entry)

    finally:
        gh.close()

    return entries


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    repo_root = Path(__file__).resolve().parent.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        default=str(repo_root / "backend" / "data" / "skill_sources.json"),
        help="Path to sources JSON (default: backend/data/skill_sources.json)",
    )
    parser.add_argument(
        "--out",
        default=str(repo_root / "backend" / "data" / "github_skill_registry.json"),
        help="Output registry path",
    )
    parser.add_argument(
        "--per-repo-cap",
        type=int,
        default=DEFAULT_PER_REPO_CAP,
        help="Max SKILL.md files to include from any single repo.",
    )
    args = parser.parse_args()

    sources = _load_sources(Path(args.sources))
    if not sources:
        logger.error("no sources found — aborting")
        return 1

    logger.info("crawling %d repo(s)...", len(sources))
    entries = crawl(sources, per_repo_cap=args.per_repo_cap)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "description": "Auto-crawled from GitHub repos declared in skill_sources.json.",
        "sources": [f"{s['owner']}/{s['repo']}" for s in sources],
        "skills": entries,
    }
    out_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    by_repo: Dict[str, int] = {}
    for e in entries:
        by_repo[e["source_repo"]] = by_repo.get(e["source_repo"], 0) + 1

    print(f"\n✓ wrote {out_path.relative_to(repo_root)}")
    print(f"  {len(entries)} skills from {len(by_repo)} repo(s):")
    for repo_name, n in sorted(by_repo.items(), key=lambda x: -x[1]):
        print(f"    {n:>4d}  {repo_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
