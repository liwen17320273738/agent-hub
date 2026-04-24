"""Runtime translation service for dynamic user/AI-generated content.

Unlike the static i18n bundles (src/i18n/*.ts) which cover fixed UI strings
we know at build time, this service handles strings that only appear at
runtime: task titles, AI-generated summaries, SKILL.md descriptions loaded
from disk, etc.

Design goals
------------
* **Cheap**: every translated pair is cached on disk; we never pay twice.
* **Isolated**: failures fall back to the original text; UI keeps rendering.
* **Provider-agnostic**: reuses ``chat_completion`` so whichever LLM the
  operator has configured (Zhipu / DeepSeek / OpenAI / local) just works.
* **Safe for short UI copy**: the prompt is tight and we cap both sides to
  reduce hallucination surface on title-sized input (< 500 chars typical).

Cache
-----
Keyed by ``(normalized_text, target_lang)``. Stored as a single JSON file
at ``backend/data/translate_cache.json`` to avoid introducing a new DB
table and keep the feature trivially inspectable / wipeable (``rm`` the
file, it rebuilds).

The cache is append-only for this process: concurrent reads are safe;
concurrent writes are serialized by an asyncio lock so the file never
truncates mid-write.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from .llm_router import chat_completion

logger = logging.getLogger(__name__)

# Persistent cache lives next to skill_sources.json so backups/ops tooling
# picks it up automatically.
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "translate_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

GLOSSARY_PATH = Path(__file__).resolve().parents[2] / "data" / "translate_glossary.json"

SUPPORTED_TARGETS = {"en", "ja", "ko", "zh"}

_LANG_NAMES = {
    "en": "English",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "zh": "Simplified Chinese (简体中文)",
}

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")

# In-memory view of the cache (sync on startup, persist on write).
_cache: Dict[str, str] = {}
_cache_loaded = False
_write_lock = asyncio.Lock()

# Optional human-curated overrides: exact Chinese (or source) phrase → per-locale.
# See data/translate_glossary.json — edit without redeploying code.
_glossary: Dict[str, Dict[str, str]] = {}
_glossary_loaded = False


def _load_cache_sync() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    try:
        if CACHE_PATH.exists():
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if not isinstance(_cache, dict):
                _cache = {}
    except Exception as exc:  # noqa: BLE001 - corrupt cache is recoverable
        logger.warning("translate cache corrupt, starting fresh: %s", exc)
        _cache = {}
    _cache_loaded = True


def _load_glossary_sync() -> None:
    global _glossary, _glossary_loaded
    if _glossary_loaded:
        return
    try:
        if GLOSSARY_PATH.exists():
            raw = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if not isinstance(v, dict):
                        continue
                    out: Dict[str, str] = {}
                    for lang, s in v.items():
                        if lang in SUPPORTED_TARGETS and isinstance(s, str) and s.strip():
                            out[lang] = s.strip()
                    if out:
                        _glossary[k.strip()] = out
    except Exception as exc:  # noqa: BLE001
        logger.warning("translate glossary load failed: %s", exc)
    _glossary_loaded = True


def _glossary_get(text: str, target: str) -> Optional[str]:
    _load_glossary_sync()
    s = (text or "").strip()
    if not s:
        return None
    row = _glossary.get(s)
    if not row:
        return None
    return row.get(target)


async def _flush_cache() -> None:
    """Serialize the in-memory cache to disk under a lock."""
    async with _write_lock:
        tmp = CACHE_PATH.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CACHE_PATH)
        except Exception as exc:  # noqa: BLE001
            logger.warning("translate cache write failed: %s", exc)


def _cache_key(text: str, target: str) -> str:
    # SHA-1 is plenty for a content-addressable cache key; we're not doing
    # anything security-sensitive here and short keys keep JSON small.
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{target}:{h}"


def _needs_translation(text: str, target: str) -> bool:
    """Heuristic: skip obvious no-ops.

    * Empty / whitespace-only
    * Target is zh and text already contains Han characters
    * Target is non-zh and text has zero Han characters AND only ASCII
      (assume it's already English / code / URL)
    """
    s = (text or "").strip()
    if not s:
        return False
    has_han = bool(_HAN_RE.search(s))
    if target == "zh":
        return not has_han
    # Non-zh: if no Han and pure ASCII, it's probably already usable.
    if not has_han and s.isascii():
        return False
    return True


async def translate_text(text: str, target: str) -> str:
    """Return ``text`` translated to ``target`` (BCP-47 short: en/ja/ko/zh).

    * Cache hit → returned immediately.
    * Heuristic determines we don't need translation → original returned.
    * LLM call failure → original returned (never raise to the caller).
    """
    _load_cache_sync()

    if target not in SUPPORTED_TARGETS:
        return text
    if not _needs_translation(text, target):
        return text

    gloss = _glossary_get(text, target)
    if gloss is not None:
        # Mirror into the LLM cache so the JSON file can be pruned and we
        # still have hot-path fast lookups + consistent stats.
        k = _cache_key(text, target)
        if k not in _cache:
            _cache[k] = gloss
            asyncio.create_task(_flush_cache())
        return gloss

    key = _cache_key(text, target)
    if key in _cache:
        return _cache[key]

    system_prompt = (
        "You are a precise UI translator. Translate the user text to "
        f"{_LANG_NAMES[target]}. "
        "Rules: (1) preserve placeholders like {n}, {name}, {stage}; "
        "(2) preserve numbers, hashes, URLs, code fences and identifiers; "
        "(3) keep the result at roughly the same length; "
        "(4) output ONLY the translation, no quotes, no explanation."
    )

    try:
        res = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text[:4000]},
            ],
            temperature=0.0,
            max_tokens=800,
        )
    except Exception as exc:  # noqa: BLE001 - network / provider issues
        logger.warning("translate LLM error: %s", exc)
        return text

    if res.get("error"):
        logger.warning("translate error from provider: %s", str(res.get("error"))[:200])
        return text

    translated = (res.get("content") or "").strip()
    # Strip wrapping quotes / code fences that some models add.
    if translated.startswith("```"):
        translated = re.sub(r"^```[a-z]*\n?|```$", "", translated, flags=re.MULTILINE).strip()
    if len(translated) >= 2 and translated[0] == translated[-1] and translated[0] in {'"', "'", "「", "『"}:
        translated = translated[1:-1].strip()

    if not translated:
        return text

    _cache[key] = translated
    # Fire-and-forget flush; another concurrent call will coalesce.
    asyncio.create_task(_flush_cache())
    return translated


async def translate_batch(texts: list[str], target: str) -> list[str]:
    """Translate a list of strings. Each is cached individually.

    Uses ``asyncio.gather`` but we don't overwhelm the provider — typical
    batch size from the frontend is <= 20.
    """
    if not texts:
        return []
    return await asyncio.gather(*(translate_text(t, target) for t in texts))


def cache_stats() -> dict:
    """Lightweight introspection for /health-like endpoints."""
    _load_cache_sync()
    _load_glossary_sync()
    per_target: Dict[str, int] = {}
    for key in _cache:
        lang = key.split(":", 1)[0]
        per_target[lang] = per_target.get(lang, 0) + 1
    return {
        "total": len(_cache),
        "per_target": per_target,
        "file": str(CACHE_PATH),
        "glossary_phrases": len(_glossary),
        "glossary_file": str(GLOSSARY_PATH),
    }


async def prewarm_from_recent_task_titles() -> None:
    """Background job: pre-fill translate cache from recent `pipeline_tasks.title`.

    Respects `settings.translate_pregen_enabled`, limit, and comma target list.
    Batches small parallel slices to avoid hammering the LLM provider.
    """
    from ..config import settings

    if not settings.translate_pregen_enabled:
        return

    tlist = [x.strip() for x in (settings.translate_pregen_targets or "en").split(",")]
    targets: List[str] = [x for x in tlist if x in SUPPORTED_TARGETS and x != "zh"]
    if not targets:
        return

    limit = max(1, min(500, int(settings.translate_pregen_limit or 80)))

    try:
        from sqlalchemy import desc, select

        from ..database import async_session
        from ..models.pipeline import PipelineTask

        async with async_session() as db:
            r = await db.execute(
                select(PipelineTask.title)
                .order_by(desc(PipelineTask.updated_at))
                .limit(limit * 3),
            )
            raw_titles: List[str] = [row[0] for row in r.all() if row[0]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("translate pregen: DB read failed: %s", exc)
        return

    seen: set[str] = set()
    titles: List[str] = []
    for t in raw_titles:
        t = (t or "").strip()
        if not t or t in seen:
            continue
        if not _HAN_RE.search(t):
            continue
        seen.add(t)
        titles.append(t)
        if len(titles) >= limit:
            break

    if not titles:
        logger.info("translate pregen: no Chinese task titles in window; skip")
        return

    CHUNK = 6
    for tgt in targets:
        for i in range(0, len(titles), CHUNK):
            chunk = titles[i : i + CHUNK]
            try:
                await translate_batch(chunk, tgt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("translate pregen batch failed target=%s: %s", tgt, exc)
            await asyncio.sleep(0.15)
    logger.info("translate pregen: warmed %d titles × %s", len(titles), targets)
