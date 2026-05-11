"""
Base Vector Engine - Abstract interface for vector storage backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VectorCollection:
    """Vector collection metadata"""
    name: str
    dimension: int
    engine: str = "pgvector"
    metric: str = "cosine"
    description: str = ""
    metadata_fields: List[Dict[str, Any]] = field(default_factory=list)
    total_vectors: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class VectorRecord:
    """A single vector record"""
    id: str
    vector: List[float]
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    collection: str = ""
    created_at: Optional[str] = None
    score: float = 0.0


@dataclass
class SearchResult:
    """Search result with score"""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    collection: str = ""


@dataclass
class BatchSearchResult:
    """Results from batch search across multiple collections"""
    query: str
    results: Dict[str, List[SearchResult]] = field(default_factory=dict)
    total_hits: int = 0
    search_time_ms: int = 0


class BaseVectorEngine(ABC):
    """
    Abstract base class for vector storage engines.
    
    Implementations must provide methods for:
    - Collection management (create, delete, list)
    - Vector CRUD (insert, upsert, delete, get)
    - Similarity search (search, batch_search)
    """
    
    engine_name: str = "base"
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the engine, create tables/collections if needed"""
        pass
    
    @abstractmethod
    async def create_collection(
        self,
        name: str,
        dimension: int,
        metric: str = "cosine",
        metadata_fields: Optional[List[Dict[str, Any]]] = None,
    ) -> VectorCollection:
        """Create a new vector collection"""
        pass
    
    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """Delete a vector collection"""
        pass
    
    @abstractmethod
    async def list_collections(self) -> List[VectorCollection]:
        """List all vector collections"""
        pass
    
    @abstractmethod
    async def get_collection(self, name: str) -> Optional[VectorCollection]:
        """Get collection metadata"""
        pass
    
    @abstractmethod
    async def insert(
        self,
        collection: str,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Insert vectors into a collection"""
        pass
    
    @abstractmethod
    async def upsert(
        self,
        collection: str,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Insert or update vectors in a collection"""
        pass
    
    @abstractmethod
    async def delete(
        self,
        collection: str,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Delete vectors from a collection"""
        pass
    
    @abstractmethod
    async def get(
        self,
        collection: str,
        ids: List[str],
        include_vectors: bool = False,
    ) -> List[VectorRecord]:
        """Get vectors by IDs"""
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    async def count(self, collection: str) -> int:
        """Count vectors in a collection"""
        pass
