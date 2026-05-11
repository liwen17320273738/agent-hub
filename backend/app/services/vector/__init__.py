"""
Vector Search Service - Gateway, Embedding, and Engine abstraction.

Implements pgvector-based vector search with optional Qdrant integration.
"""
from .gateway import VectorSearchGateway, get_vector_gateway
from .embedding import EmbeddingService, get_embedding_service
from .engines.base import BaseVectorEngine, VectorCollection, VectorRecord

__all__ = [
    "VectorSearchGateway",
    "get_vector_gateway",
    "EmbeddingService",
    "get_embedding_service",
    "BaseVectorEngine",
    "VectorCollection",
    "VectorRecord",
]
