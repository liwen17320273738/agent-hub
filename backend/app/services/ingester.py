"""
Ingester — scrape/chunk/index web content into KnowledgeCollection + TaskMemory.

Pipeline:
  1. Accept a URL (or sitemap root)
  2. Call firecrawl API (or any MCP web tool) to get markdown
  3. Split into chunks
  4. Write each chunk as a TaskMemory row scoped to a KnowledgeCollection
  5. Update the KnowledgeCollection metadata (item_count, source_uri)

This service is NOT a background worker yet — it runs synchronously in the
request context. When throughput grows (many concurrent scrapes), promote
it to a Celery / RQ / arq task queue.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..database import async_session_factory
from ..models.memory import KnowledgeCollection, TaskMemory
from .memory import store_memory

logger = logging.getLogger(__name__)

# ── Chunking ──────────────────────────────────────────────────────────────

MIN_CHUNK_LEN = 200
MAX_CHUNK_LEN = 2000
OVERLAP = 100


def _chunk_markdown(text: str) -> List[str]:
    """Split markdown into reasonable chunks by heading boundaries.

    Strategy:
      - Split on ## or ### headings (keep heading in chunk)
      - If a chunk is still > MAX_CHUNK_LEN, split on double-newlines
      - If still too long, hard-split at MAX_CHUNK_LEN with overlap
    """
    if not text or len(text.strip()) < MIN_CHUNK_LEN:
        return [text] if text else []

    chunks: List[str] = []
    parts = re.split(r'(?=^##\s|^###\s)', text, flags=re.MULTILINE)

    current = ""
    for part in parts:
        if not part.strip():
            continue
        if len(current) + len(part) < MAX_CHUNK_LEN:
            current += part
        else:
            if current.strip():
                chunks.append(current.strip())
            # New section, but could still be huge
            if len(part) > MAX_CHUNK_LEN:
                sub_parts = re.split(r'\n\n', part)
                for sp in sub_parts:
                    if len(sp) > MAX_CHUNK_LEN:
                        # Hard split
                        for i in range(0, len(sp), MAX_CHUNK_LEN - OVERLAP):
                            seg = sp[i:i + MAX_CHUNK_LEN].strip()
                            if len(seg) >= MIN_CHUNK_LEN:
                                chunks.append(seg)
                    elif len(sp) >= MIN_CHUNK_LEN:
                        chunks.append(sp.strip())
                    current = ""
            else:
                current = part

    if current.strip() and len(current.strip()) >= MIN_CHUNK_LEN:
        chunks.append(current.strip())

    return chunks or [text[:MAX_CHUNK_LEN]]


# ── Firecrawl API call ────────────────────────────────────────────────────

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


async def _firecrawl_scrape(url: str, api_key: str) -> Optional[str]:
    """Scrape a single URL via Firecrawl REST API.

    Returns the markdown content, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "formats": ["markdown"]},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.warning(f"[ingester] firecrawl returned success=false: {data}")
                return None
            md = data.get("data", {}).get("markdown", "")
            return md if len(md.strip()) >= MIN_CHUNK_LEN else None
    except Exception as e:
        logger.warning(f"[ingester] firecrawl scrape failed for {url}: {e}")
        return None


# ── Public API ────────────────────────────────────────────────────────────


async def ingest_url(
    url: str,
    api_key: str,
    *,
    collection_name: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
    org_id: Optional[UUID] = None,
    created_by: str = "ingester",
) -> Dict[str, Any]:
    """Scrape a URL, chunk, and index into a KnowledgeCollection.

    Returns a summary dict with collection_id, item_count, and any errors.
    """
    md = await _firecrawl_scrape(url, api_key)
    if not md:
        return {"ok": False, "error": f"Failed to scrape {url}", "url": url}

    async with async_session_factory() as db:
        # 1. Create or get collection
        col_name = collection_name or f"scraped-{_slugify(url)[:40]}"
        existing = await _find_collection_by_name(db, col_name, org_id)
        if existing:
            collection = existing
        else:
            collection = KnowledgeCollection(
                name=col_name,
                description=f"Auto-ingested from {url}",
                source_type="web_scrape",
                source_uri=url,
                access_scope="workspace",
                workspace_id=workspace_id,
                org_id=org_id,
                created_by=created_by,
            )
            db.add(collection)
            await db.flush()

        # 2. Chunk and store
        chunks = _chunk_markdown(md)
        stored = 0
        errors: List[str] = []
        for i, chunk in enumerate(chunks):
            try:
                title = f"{collection.name} — chunk {i+1}"
                mem = await store_memory(
                    db,
                    task_id=f"ingest:{collection.id}",
                    stage_id="ingestion",
                    role="ingester",
                    title=title,
                    content=chunk,
                    tags=[collection.name, url, "web_scrape"],
                    quality_score=0.7,
                )
                if mem:
                    mem.collection_id = collection.id
                    stored += 1
            except Exception as e:
                errors.append(f"chunk {i+1}: {e}")

        # 3. Update collection metadata
        collection.item_count = stored
        await db.flush()
        await db.commit()

    logger.info(
        f"[ingester] Ingested {stored}/{len(chunks)} chunks from {url} "
        f"into collection={collection.id} name={collection.name}"
    )

    return {
        "ok": True,
        "collection_id": str(collection.id),
        "collection_name": collection.name,
        "source_uri": url,
        "chunks_total": len(chunks),
        "chunks_stored": stored,
        "errors": errors[:5],
    }


async def _find_collection_by_name(
    db, name: str, org_id: Optional[UUID] = None,
) -> Optional[KnowledgeCollection]:
    """Find an active collection by name (scoped to org if present)."""
    from sqlalchemy import select

    stmt = select(KnowledgeCollection).where(
        KnowledgeCollection.name == name,
        KnowledgeCollection.is_active.is_(True),
    )
    if org_id:
        stmt = stmt.where(KnowledgeCollection.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _slugify(url: str) -> str:
    """Make a short slug from a URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")
    # Take last meaningful segment
    segs = [s for s in path.split("/") if s and not s.startswith(".")]
    slug = (segs[-1] if segs else parsed.netloc).replace("-", "_").replace(".", "_")
    return re.sub(r"[^a-zA-Z0-9_]", "", slug)[:40] or "site"
