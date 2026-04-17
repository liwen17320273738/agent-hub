"""add ivfflat index on code_chunks.embedding (PG + pgvector only)

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-04-17 17:00:00.000000

Creates an IVFFlat ANN index for fast cosine similarity search on the
`code_chunks.embedding` column. No-op on SQLite or when the pgvector
extension isn't installed — the application's Python-side cosine path
keeps working without it.

Why IVFFlat (and not HNSW):
- Available in pgvector >= 0.4 (HNSW needs 0.5+)
- Build is much faster, training-friendly for smaller corpora (< 1M rows)
- Cosine distance operator class: `vector_cosine_ops`
- `lists` chosen as sqrt(estimated_rows) — defaults to 100 here; tune
  to ~rows/1000 for production datasets via a manual REINDEX.
"""
from alembic import op
import sqlalchemy as sa


revision = "1b2c3d4e5f6a"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Probe pgvector availability — without it the column is TEXT and an
    # IVFFlat index would fail. Skip silently in that case.
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        ext = bind.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
        if not ext:
            return
    except Exception:
        return

    # Detect actual column type — when the pre-existing column is TEXT (the
    # default the previous migration created), we must convert it to
    # `vector(dim)` first. Use a dim that matches whatever's already stored;
    # default to 1536 (OpenAI text-embedding-3-small) if empty.
    has_rows = bind.execute(
        sa.text("SELECT 1 FROM code_chunks LIMIT 1")
    ).first()

    coltype = bind.execute(sa.text("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'code_chunks' AND column_name = 'embedding'
    """)).scalar()

    if coltype and coltype.lower() == "text" and not has_rows:
        # Safe to alter when the table is empty.
        op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(1536) USING NULL")
    elif coltype and coltype.lower() == "text":
        # Existing TEXT-stored rows can't be auto-coerced; leave the column
        # as TEXT and emit a notice. Operators should drop+reindex the
        # project to repopulate as native vectors.
        op.execute(
            "DO $$ BEGIN RAISE NOTICE "
            "'code_chunks.embedding kept as TEXT (existing rows). "
            "Drop a project and reindex to use pgvector ANN.';"
            " END $$"
        )
        return

    # Create IVFFlat index with cosine ops; lists=100 is a fine starting
    # point for up to ~100k rows. CONCURRENTLY skipped because alembic
    # wraps the migration in a transaction.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_ivfflat "
        "ON code_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_ivfflat")
    # Don't auto-revert the column type back to TEXT — that would lose data
    # in production.
