"""Codebase semantic indexer.

Walks a project tree, slices source files into ~600-token chunks, embeds
each chunk via `llm_router.create_embeddings`, and upserts into the
`code_chunks` table. A subsequent semantic search call computes cosine
similarity in Python and returns the top-K hits.

Design notes:
- Reuses skip lists / extension allow-lists from `tools.codebase_index`
  so behaviour stays consistent with the literal search tool.
- Chunks are file-line slices (not AST), keeping the indexer language-
  agnostic. ~40 lines / chunk gives ~500-800 tokens for typical code.
- `content_hash = sha256(text)` lets reindex skip unchanged chunks.
- Embedding column is JSON text by default → portable across SQLite/PG
  without pgvector. For datasets >100k chunks switch to pgvector +
  `enable_pgvector(True)` and a separate ANN index migration.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..compat import is_pgvector_enabled
from ..models.code_chunk import CodeChunk
from .llm_router import create_embeddings
from .tools.codebase_index import (
    _INDEXABLE_EXTS, _extract_symbols,
    _should_skip_dir, _should_skip_file, _is_indexable,
)
from ..config import settings

logger = logging.getLogger(__name__)

CHUNK_LINES = 40        # ~500-800 tokens; balanced for retrieval granularity
CHUNK_OVERLAP = 8       # repeat last 8 lines so identifiers spanning a split still hit
MAX_TEXT_PER_CHUNK = 4000  # safety cap when a "line" is enormous (minified files)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _slice_chunks(content: str) -> List[Tuple[int, int, str]]:
    """Slice file content into overlapping line windows.

    Returns [(start_line_1based, end_line_1based, text), ...].
    Skips empty trailing chunks.
    """
    lines = content.splitlines()
    if not lines:
        return []
    out: List[Tuple[int, int, str]] = []
    step = max(1, CHUNK_LINES - CHUNK_OVERLAP)
    i = 0
    n = len(lines)
    while i < n:
        end = min(n, i + CHUNK_LINES)
        text = "\n".join(lines[i:end])
        if text.strip():
            out.append((i + 1, end, text[:MAX_TEXT_PER_CHUNK]))
        if end >= n:
            break
        i += step
    return out


def _walk(project_dir: Path, max_files: int) -> Iterable[Path]:
    count = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for fname in files:
            if count >= max_files:
                return
            yield Path(root) / fname
            count += 1


def _language_tag(path: Path) -> str:
    suf = path.suffix.lower().lstrip(".")
    if not suf and path.name in _INDEXABLE_EXTS:
        return path.name.lower()
    return suf or ""


async def reindex_project(
    db: AsyncSession,
    *,
    project_dir: str,
    project_id: Optional[str] = None,
    max_files: Optional[int] = None,
    embedding_model: str = "",
    embedding_provider: str = "",
) -> Dict[str, Any]:
    """Walk, chunk, embed, and upsert. Returns a summary report.

    Skips chunks whose `content_hash` is already present for this project_id
    (idempotent reindex).
    """
    started = time.monotonic()
    root = Path(project_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": f"project_dir not found: {project_dir}"}

    pid = project_id or str(root)
    cap = int(max_files or settings.codebase_index_max_files)
    max_bytes = int(settings.codebase_index_max_file_kb) * 1024

    # Pull existing hashes once so we can dedupe without N round-trips.
    existing_rows = await db.execute(
        select(CodeChunk.content_hash, CodeChunk.rel_path).where(CodeChunk.project_id == pid)
    )
    existing: set[Tuple[str, str]] = set()
    for h, rp in existing_rows.all():
        existing.add((rp, h))

    pending: List[Dict[str, Any]] = []
    files_scanned = 0
    files_skipped = 0

    for path in _walk(root, cap):
        if _should_skip_file(path, max_bytes):
            files_skipped += 1
            continue
        if not _is_indexable(path):
            files_skipped += 1
            continue
        files_scanned += 1
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = path.relative_to(root).as_posix()
        symbols = _extract_symbols(path, content, limit=8)
        for start, end, text in _slice_chunks(content):
            h = _hash(text)
            if (rel, h) in existing:
                continue
            pending.append({
                "project_id": pid,
                "rel_path": rel,
                "language": _language_tag(path),
                "start_line": start,
                "end_line": end,
                "content_hash": h,
                "text": text,
                "symbols": symbols,
            })

    if not pending:
        return {
            "ok": True,
            "project_id": pid,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "chunks_new": 0,
            "chunks_skipped_unchanged": True,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    # Embed in batches via the router.
    texts = [p["text"] for p in pending]
    emb = await create_embeddings(
        texts, model=embedding_model, provider=embedding_provider,
    )
    if not emb.get("ok"):
        return {
            "ok": False,
            "error": f"embeddings failed: {emb.get('error')}",
            "files_scanned": files_scanned,
            "chunks_attempted": len(pending),
        }

    vectors = emb.get("vectors") or []
    if len(vectors) != len(pending):
        return {
            "ok": False,
            "error": f"vector count mismatch: got {len(vectors)} want {len(pending)}",
        }

    dim = emb.get("dim") or 0
    model = emb.get("model") or ""

    # Upsert: delete old rows for the same (project_id, rel_path, content_hash)
    # is unnecessary because we deduped against `existing` already. Just
    # insert the fresh chunks.
    bulk: List[CodeChunk] = []
    for p, vec in zip(pending, vectors):
        bulk.append(CodeChunk(
            project_id=p["project_id"],
            rel_path=p["rel_path"],
            language=p["language"],
            start_line=p["start_line"],
            end_line=p["end_line"],
            content_hash=p["content_hash"],
            text=p["text"],
            symbols=p["symbols"],
            embedding=vec,
            embedding_model=model,
            embedding_dim=dim,
        ))
    db.add_all(bulk)
    await db.commit()

    return {
        "ok": True,
        "project_id": pid,
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "chunks_new": len(bulk),
        "embedding_model": model,
        "embedding_dim": dim,
        "tokens_used": int((emb.get("usage") or {}).get("total_tokens") or 0),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


async def drop_project(db: AsyncSession, project_id: str) -> Dict[str, Any]:
    """Delete all chunks for a project (e.g. before a fresh full reindex)."""
    result = await db.execute(
        delete(CodeChunk).where(CodeChunk.project_id == project_id)
    )
    await db.commit()
    return {"ok": True, "project_id": project_id, "deleted": result.rowcount or 0}


async def project_stats(db: AsyncSession, project_id: str) -> Dict[str, Any]:
    """Quick counters: chunk count, distinct files, embedding model in use."""
    rows = await db.execute(
        select(CodeChunk.rel_path, CodeChunk.embedding_model, CodeChunk.embedding_dim)
        .where(CodeChunk.project_id == project_id)
    )
    rels: set[str] = set()
    model = ""
    dim = 0
    total = 0
    for rel, m, d in rows.all():
        total += 1
        rels.add(rel)
        if m and not model:
            model = m
            dim = d or 0
    return {
        "ok": True,
        "project_id": project_id,
        "chunks": total,
        "files": len(rels),
        "embedding_model": model,
        "embedding_dim": dim,
    }


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


async def semantic_search(
    db: AsyncSession,
    *,
    project_id: str,
    query: str,
    top_k: int = 5,
    embedding_model: str = "",
    embedding_provider: str = "",
) -> Dict[str, Any]:
    """Embed `query`, scan all chunks for this project, return top-K by cosine.

    Python-side scan is O(N·dim). Fine for a single repo (≤ 50k chunks);
    swap to pgvector + ivfflat for bigger corpora.
    """
    if not query.strip():
        return {"ok": False, "error": "empty query"}
    started = time.monotonic()

    qe = await create_embeddings([query], model=embedding_model, provider=embedding_provider)
    if not qe.get("ok") or not qe.get("vectors"):
        return {"ok": False, "error": f"query embedding failed: {qe.get('error')}"}
    qvec: List[float] = qe["vectors"][0]
    qdim = len(qvec)
    k = max(1, min(top_k, 50))

    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    use_pg_ann = dialect_name == "postgresql" and is_pgvector_enabled()

    if use_pg_ann:
        try:
            sql = sa_text(
                """
                SELECT id, rel_path, start_line, end_line, language, symbols, text,
                       1 - (embedding <=> CAST(:qvec AS vector)) AS score
                FROM code_chunks
                WHERE project_id = :pid AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:qvec AS vector)
                LIMIT :k
                """
            )
            res = await db.execute(sql, {"qvec": qvec, "pid": project_id, "k": k})
            rows = res.mappings().all()
            if not rows:
                return {"ok": True, "project_id": project_id, "query": query, "hits": [],
                        "reason": "no chunks indexed", "backend": "pgvector"}
            hits = [
                {
                    "rel_path": r["rel_path"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"],
                    "score": round(float(r["score"]), 4),
                    "language": r["language"],
                    "symbols": list(r["symbols"] or []),
                    "preview": (r["text"] or "")[:600],
                }
                for r in rows
            ]
            return {
                "ok": True,
                "project_id": project_id,
                "query": query,
                "hits": hits,
                "scanned_chunks": len(rows),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "backend": "pgvector",
            }
        except Exception as e:
            logger.warning("pgvector ANN search failed (%s); falling back to Python cosine", e)

    rows = await db.execute(
        select(CodeChunk).where(CodeChunk.project_id == project_id)
    )
    chunks = rows.scalars().all()
    if not chunks:
        return {"ok": True, "project_id": project_id, "query": query, "hits": [],
                "reason": "no chunks indexed", "backend": "python"}

    scored: List[Tuple[float, CodeChunk]] = []
    for c in chunks:
        vec = c.embedding
        if not vec or len(vec) != qdim:
            continue
        scored.append((_cosine(qvec, vec), c))
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:k]
    hits = [
        {
            "rel_path": c.rel_path,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "score": round(score, 4),
            "language": c.language,
            "symbols": list(c.symbols or []),
            "preview": (c.text or "")[:600],
        }
        for score, c in top
    ]
    return {
        "ok": True,
        "project_id": project_id,
        "query": query,
        "hits": hits,
        "scanned_chunks": len(chunks),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "backend": "python",
    }
