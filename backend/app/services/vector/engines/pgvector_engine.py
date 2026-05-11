"""
pgvector Engine - PostgreSQL-based vector storage.

Uses the pgvector extension for vector similarity search with HNSW indexing.
"""
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text, select

from .base import (
    BaseVectorEngine,
    VectorCollection,
    VectorRecord,
    SearchResult,
)

logger = logging.getLogger(__name__)

# ── SQL Injection Guard ──────────────────────────────────────────
# Collection / table names are interpolated into raw SQL via f-strings.
# Only allow alphanumeric + underscore to prevent injection.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def _validate_collection_name(name: str) -> str:
    """Validate a collection name is safe for SQL identifier interpolation.

    Raises ValueError if the name contains characters outside [A-Za-z0-9_]
    or is longer than 128 characters.
    """
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid collection name '{name}': "
            "must start with a letter or underscore, "
            "contain only alphanumeric characters and underscores, "
            "and be 1-128 characters long."
        )
    return name


class PgvectorEngine(BaseVectorEngine):
    """
    pgvector-based vector storage engine.
    
    Features:
    - HNSW index for fast similarity search
    - Full SQL filtering support
    - Transactional vector operations
    - JSON metadata storage
    """
    
    engine_name = "pgvector"
    
    def __init__(self, session_factory):
        """
        Initialize pgvector engine.
        
        Args:
            session_factory: Async SQLAlchemy session factory
        """
        self._session_factory = session_factory
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize pgvector extension and metadata table"""
        if self._initialized:
            return
        
        async with self._session_factory() as db:
            # Enable pgvector extension
            await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            
            # Create metadata table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS vector_collections (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    dimension INTEGER NOT NULL,
                    engine VARCHAR(50) DEFAULT 'pgvector',
                    metric VARCHAR(50) DEFAULT 'cosine',
                    description TEXT DEFAULT '',
                    metadata_fields JSONB DEFAULT '[]',
                    total_vectors INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            
            await db.commit()
        
        self._initialized = True
        logger.info("pgvector engine initialized")
    
    async def _ensure_table(self, db, collection_name: str, dimension: int) -> str:
        """Ensure the vector table exists for a collection"""
        _validate_collection_name(collection_name)
        table_name = f"vectors_{collection_name}"
        
        await db.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id VARCHAR(64) PRIMARY KEY,
                vector vector({dimension}),
                text TEXT,
                metadata JSONB DEFAULT '{{}}',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        
        return table_name
    
    async def create_collection(
        self,
        name: str,
        dimension: int,
        metric: str = "cosine",
        metadata_fields: Optional[List[Dict[str, Any]]] = None,
    ) -> VectorCollection:
        """Create a new vector collection"""
        _validate_collection_name(name)
        await self.initialize()
        
        async with self._session_factory() as db:
            # Check if exists
            result = await db.execute(
                text("SELECT name FROM vector_collections WHERE name = :name"),
                {"name": name},
            )
            existing = result.scalar()
            
            if existing:
                raise ValueError(f"Collection '{name}' already exists")
            
            # Create metadata record
            await db.execute(
                text("""
                    INSERT INTO vector_collections (name, dimension, engine, metric, description, metadata_fields)
                    VALUES (:name, :dimension, 'pgvector', :metric, '', :metadata_fields)
                """),
                {
                    "name": name,
                    "dimension": dimension,
                    "metric": metric,
                    "metadata_fields": json.dumps(metadata_fields or []),
                },
            )
            
            # Create vector table
            await self._ensure_table(db, name, dimension)
            
            # Create HNSW index
            try:
                table_name = self._safe_table(name)
                # Cosine distance is preferred for semantic search
                index_method = "vector_cosine_ops" if metric == "cosine" else "vector_l2_ops"
                await db.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{name}_vector
                    ON {table_name} USING hnsw (vector {index_method})
                    WITH (m = 16, ef_construction = 200)
                """))
                logger.info(f"Created HNSW index for collection '{name}'")
            except Exception as e:
                logger.warning(f"Could not create HNSW index: {e}")
            
            await db.commit()
        
        return VectorCollection(
            name=name,
            dimension=dimension,
            engine="pgvector",
            metric=metric,
            metadata_fields=metadata_fields or [],
            total_vectors=0,
            created_at=datetime.utcnow().isoformat(),
        )
    
    async def delete_collection(self, name: str) -> bool:
        """Delete a vector collection"""
        _validate_collection_name(name)
        await self.initialize()
        
        async with self._session_factory() as db:
            # Drop vector table
            table_name = self._safe_table(name)
            await db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            
            # Delete metadata
            await db.execute(
                text("DELETE FROM vector_collections WHERE name = :name"),
                {"name": name},
            )
            
            await db.commit()
        
        return True
    
    async def list_collections(self) -> List[VectorCollection]:
        """List all vector collections"""
        await self.initialize()
        
        async with self._session_factory() as db:
            result = await db.execute(
                text("SELECT name, dimension, engine, metric, description, metadata_fields, total_vectors, created_at FROM vector_collections ORDER BY name")
            )
            rows = result.fetchall()
        
        collections = []
        for row in rows:
            collections.append(VectorCollection(
                name=row[0],
                dimension=row[1],
                engine=row[2] or "pgvector",
                metric=row[3] or "cosine",
                description=row[4] or "",
                metadata_fields=json.loads(row[5]) if row[5] else [],
                total_vectors=row[6] or 0,
                created_at=row[7].isoformat() if row[7] else None,
            ))
        
        return collections
    
    async def get_collection(self, name: str) -> Optional[VectorCollection]:
        """Get collection metadata"""
        await self.initialize()
        
        async with self._session_factory() as db:
            result = await db.execute(
                text("SELECT name, dimension, engine, metric, description, metadata_fields, total_vectors, created_at FROM vector_collections WHERE name = :name"),
                {"name": name},
            )
            row = result.fetchone()
            
            if not row:
                return None
            
            return VectorCollection(
                name=row[0],
                dimension=row[1],
                engine=row[2] or "pgvector",
                metric=row[3] or "cosine",
                description=row[4] or "",
                metadata_fields=json.loads(row[5]) if row[5] else [],
                total_vectors=row[6] or 0,
                created_at=row[7].isoformat() if row[7] else None,
            )
    
    def _safe_table(self, collection: str) -> str:
        """Return a validated table name for the given collection."""
        _validate_collection_name(collection)
        return f"vectors_{collection}"

    async def insert(
        self,
        collection: str,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Insert vectors into a collection"""
        await self.initialize()
        
        if len(vectors) != len(texts):
            raise ValueError("vectors and texts must have the same length")
        
        # Generate IDs if not provided
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            
            for i, vector in enumerate(vectors):
                vector_str = f"[{','.join(str(v) for v in vector)}]"
                metadata = json.dumps(metadatas[i] if metadatas else {})
                
                await db.execute(
                    text(f"""
                        INSERT INTO {table_name} (id, vector, text, metadata)
                        VALUES (:id, :vector, :text, :metadata)
                    """),
                    {
                        "id": ids[i],
                        "vector": vector_str,
                        "text": texts[i],
                        "metadata": metadata,
                    },
                )
            
            # Update count
            await db.execute(
                text("""
                    UPDATE vector_collections 
                    SET total_vectors = (SELECT COUNT(*) FROM """ + table_name + """),
                        updated_at = NOW()
                    WHERE name = :name
                """),
                {"name": collection},
            )
            
            await db.commit()
        
        return ids
    
    async def upsert(
        self,
        collection: str,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Insert or update vectors"""
        await self.initialize()
        
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            
            for i, vector in enumerate(vectors):
                vector_str = f"[{','.join(str(v) for v in vector)}]"
                metadata = json.dumps(metadatas[i] if metadatas else {})
                
                await db.execute(
                    text(f"""
                        INSERT INTO {table_name} (id, vector, text, metadata)
                        VALUES (:id, :vector, :text, :metadata)
                        ON CONFLICT (id) DO UPDATE SET
                            vector = EXCLUDED.vector,
                            text = EXCLUDED.text,
                            metadata = EXCLUDED.metadata
                    """),
                    {
                        "id": ids[i],
                        "vector": vector_str,
                        "text": texts[i],
                        "metadata": metadata,
                    },
                )
            
            await db.commit()
        
        return ids
    
    async def delete(
        self,
        collection: str,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Delete vectors from a collection"""
        await self.initialize()
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            count = 0
            
            if ids:
                for vid in ids:
                    await db.execute(
                        text(f"DELETE FROM {table_name} WHERE id = :id"),
                        {"id": vid},
                    )
                count = len(ids)
            elif where:
                # Support JSONB metadata filtering
                conditions = []
                params = {}
                for key, value in where.items():
                    # Validate metadata key to prevent SQL injection
                    if not _SAFE_NAME_RE.match(key):
                        raise ValueError(
                            f"Invalid metadata key '{key}': "
                            "must match the same rules as collection names."
                        )
                    conditions.append(f"metadata->>'{key}' = :where_{key}")
                    params[f"where_{key}"] = str(value)
                
                if conditions:
                    result = await db.execute(
                        text(f"DELETE FROM {table_name} WHERE {' AND '.join(conditions)}"),
                        params,
                    )
                    count = result.rowcount
            
            await db.commit()
        
        return count
    
    async def get(
        self,
        collection: str,
        ids: List[str],
        include_vectors: bool = False,
    ) -> List[VectorRecord]:
        """Get vectors by IDs"""
        await self.initialize()
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            results = []
            
            for vid in ids:
                result = await db.execute(
                    text(f"SELECT id, vector, text, metadata, created_at FROM {table_name} WHERE id = :id"),
                    {"id": vid},
                )
                row = result.fetchone()
                
                if row:
                    vector = None
                    if include_vectors and row[1]:
                        vector_str = row[1].strip("[]")
                        vector = [float(v) for v in vector_str.split(",")]
                    
                    results.append(VectorRecord(
                        id=row[0],
                        vector=vector or [],
                        text=row[2] or "",
                        metadata=json.loads(row[3]) if row[3] else {},
                        collection=collection,
                        created_at=row[4].isoformat() if row[4] else None,
                    ))
        
        return results
    
    async def search(
        self,
        collection: str,
        query_vector: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        limit: int = 10,
        where: Optional[Dict[str, Any]] = None,
        include_vectors: bool = False,
    ) -> List[SearchResult]:
        """Search for similar vectors"""
        await self.initialize()
        
        if query_vector is None:
            raise ValueError("query_vector is required for pgvector search")
        
        vector_str = f"[{','.join(str(v) for v in query_vector)}]"
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            
            # Build query
            distance_expr = f"1 - (vector <=> :query_vector)"
            where_clauses = []
            params = {"query_vector": vector_str, "limit": limit}
            
            if where:
                for key, value in where.items():
                    if not _SAFE_NAME_RE.match(key):
                        raise ValueError(
                            f"Invalid metadata key '{key}': "
                            "must match the same rules as collection names."
                        )
                    where_clauses.append(f"metadata->>'{key}' = :where_{key}")
                    params[f"where_{key}"] = str(value)
            
            where_sql = ""
            if where_clauses:
                where_sql = "AND " + " AND ".join(where_clauses)
            
            query = text(f"""
                SELECT id, text, metadata, {distance_expr} as similarity
                FROM {table_name}
                WHERE 1=1 {where_sql}
                ORDER BY vector <=> :query_vector
                LIMIT :limit
            """)
            
            result = await db.execute(query, params)
            rows = result.fetchall()
        
        results = []
        for row in rows:
            results.append(SearchResult(
                id=row[0],
                text=row[1] or "",
                score=float(row[3]) if row[3] else 0.0,
                metadata=json.loads(row[2]) if row[2] else {},
                collection=collection,
            ))
        
        return results
    
    async def count(self, collection: str) -> int:
        """Count vectors in a collection"""
        await self.initialize()
        
        async with self._session_factory() as db:
            table_name = self._safe_table(collection)
            result = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = result.scalar()
        
        return count or 0
