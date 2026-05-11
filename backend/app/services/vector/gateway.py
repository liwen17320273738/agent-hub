"""
Vector Search Gateway - Unified entry point for vector operations.

Routes requests to pgvector (primary) or Qdrant (specialized) based on
collection configuration and query requirements.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from .engines.base import BaseVectorEngine, VectorCollection, SearchResult, BatchSearchResult
from .engines.pgvector_engine import PgvectorEngine
from .embedding import get_embedding_service

logger = logging.getLogger(__name__)


class VectorSearchGateway:
    """
    Vector Search Gateway - unified interface for vector operations.
    
    Features:
    - Automatic engine routing (pgvector default, Qdrant for specialized workloads)
    - Embedding generation and caching
    - Batch operations across collections
    - Metadata filtering
    """
    
    def __init__(self, session_factory):
        """
        Initialize vector search gateway.
        
        Args:
            session_factory: Async SQLAlchemy session factory
        """
        self._pgvector = PgvectorEngine(session_factory)
        self._embedding = get_embedding_service()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize engines"""
        if self._initialized:
            return
        
        await self._pgvector.initialize()
        self._initialized = True
        logger.info("Vector search gateway initialized")
    
    def _get_engine(self, collection: Optional[str] = None) -> BaseVectorEngine:
        """Get the appropriate engine for a collection"""
        # Default to pgvector for now
        # In future: check collection config for Qdrant routing
        return self._pgvector
    
    # ─────────────────────────────────────────────────────────────────────
    # Collection Management
    # ─────────────────────────────────────────────────────────────────────
    
    async def create_collection(
        self,
        name: str,
        dimension: int = 1536,
        metric: str = "cosine",
        metadata_fields: Optional[List[Dict[str, Any]]] = None,
    ) -> VectorCollection:
        """Create a vector collection"""
        await self.initialize()
        engine = self._get_engine()
        return await engine.create_collection(name, dimension, metric, metadata_fields)
    
    async def list_collections(self) -> List[VectorCollection]:
        """List all collections"""
        await self.initialize()
        engine = self._get_engine()
        return await engine.list_collections()
    
    async def delete_collection(self, name: str) -> bool:
        """Delete a collection"""
        await self.initialize()
        engine = self._get_engine()
        return await engine.delete_collection(name)
    
    # ─────────────────────────────────────────────────────────────────────
    # Vector CRUD
    # ─────────────────────────────────────────────────────────────────────
    
    async def add_texts(
        self,
        collection: str,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Add texts to a collection (auto-generates embeddings).
        
        Args:
            collection: Collection name
            texts: Texts to embed and store
            metadatas: Optional metadata for each text
            ids: Optional IDs
            
        Returns:
            List of stored vector IDs
        """
        await self.initialize()
        
        # Generate embeddings
        embeddings = await self._embedding.embed(texts)
        
        # Store vectors
        engine = self._get_engine(collection)
        return await engine.insert(collection, embeddings, texts, metadatas, ids)
    
    async def add_text(
        self,
        collection: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
    ) -> str:
        """Add a single text to a collection"""
        ids = await self.add_texts(collection, [text], [metadata] if metadata else None, [id] if id else None)
        return ids[0] if ids else ""
    
    async def delete_by_ids(self, collection: str, ids: List[str]) -> int:
        """Delete vectors by IDs"""
        await self.initialize()
        engine = self._get_engine(collection)
        return await engine.delete(collection, ids=ids)
    
    async def delete_by_metadata(self, collection: str, where: Dict[str, Any]) -> int:
        """Delete vectors by metadata filter"""
        await self.initialize()
        engine = self._get_engine(collection)
        return await engine.delete(collection, where=where)
    
    # ─────────────────────────────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────────────────────────────
    
    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        Search for similar texts in a collection.
        
        Args:
            collection: Collection name
            query: Query text
            limit: Maximum results
            where: Metadata filter
            
        Returns:
            List of search results with scores
        """
        await self.initialize()
        
        start_time = time.time()
        
        # Generate query embedding
        query_vector = await self._embedding.embed_one(query)
        
        # Search
        engine = self._get_engine(collection)
        results = await engine.search(
            collection=collection,
            query_vector=query_vector,
            limit=limit,
            where=where,
        )
        
        search_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"Search '{query[:50]}...' in {collection}: {len(results)} results in {search_ms}ms")
        
        return results
    
    async def search_multi(
        self,
        collections: List[str],
        query: str,
        limit: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> BatchSearchResult:
        """Search across multiple collections"""
        await self.initialize()
        
        start_time = time.time()
        all_results = {}
        total_hits = 0
        
        for collection in collections:
            results = await self.search(collection, query, limit, where)
            all_results[collection] = results
            total_hits += len(results)
        
        search_ms = int((time.time() - start_time) * 1000)
        
        return BatchSearchResult(
            query=query,
            results=all_results,
            total_hits=total_hits,
            search_time_ms=search_ms,
        )
    
    async def search_related(
        self,
        collection: str,
        text_id: str,
        limit: int = 10,
    ) -> List[SearchResult]:
        """
        Find texts related to a specific stored text.
        
        Args:
            collection: Collection name
            text_id: ID of the reference text
            limit: Maximum results
            
        Returns:
            Related texts ordered by similarity
        """
        await self.initialize()
        
        engine = self._get_engine(collection)
        
        # Get the reference vector
        records = await engine.get(collection, [text_id], include_vectors=True)
        if not records:
            return []
        
        # Search by vector
        results = await engine.search(
            collection=collection,
            query_vector=records[0].vector,
            limit=limit + 1,  # +1 to account for the reference itself
        )
        
        # Filter out the reference text
        return [r for r in results if r.id != text_id][:limit]
    
    # ─────────────────────────────────────────────────────────────────────
    # Memory Integration
    # ─────────────────────────────────────────────────────────────────────
    
    async def store_memory(
        self,
        content: str,
        memory_type: str = "conversation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store content in vector memory.

        Args:
            content: Text content to store
            memory_type: Memory type ('conversation', 'pattern', 'fact')
            metadata: Additional metadata

        Returns:
            Vector ID
        """
        full_metadata = metadata or {}
        full_metadata["memory_type"] = memory_type
        return await self.add_text("memory", content, full_metadata)
    
    async def recall_memory(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Recall relevant memories by semantic similarity.

        Args:
            query: Search query
            limit: Maximum results
            memory_type: Filter by memory type

        Returns:
            Relevant memories
        """
        where = {"memory_type": memory_type} if memory_type else None
        return await self.search("memory", query, limit, where)


# Singleton
_vector_gateway: Optional[VectorSearchGateway] = None


def get_vector_gateway(session_factory=None) -> VectorSearchGateway:
    """Get or create the vector search gateway singleton"""
    global _vector_gateway
    if _vector_gateway is None:
        if session_factory is None:
            from ...database import async_session as default_session
            session_factory = default_session
        _vector_gateway = VectorSearchGateway(session_factory)
    return _vector_gateway
