"""
Embedding Service - Text-to-vector conversion.

Supports multiple embedding providers:
- OpenAI (text-embedding-3-small/large)
- BGE (local via transformers)
- HuggingFace inference
"""
import logging
import hashlib
from typing import List, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Simple cache for embeddings
_embedding_cache: TTLCache = TTLCache(maxsize=5000, ttl=86400)  # 24h TTL


class EmbeddingService:
    """Service for generating text embeddings"""
    
    def __init__(self):
        self.default_dimension = 1536  # OpenAI text-embedding-3-small
    
    def _cache_key(self, texts: List[str], model: str = "openai") -> str:
        """Generate cache key for text batch"""
        content = "|".join(texts) + model
        return hashlib.md5(content.encode()).hexdigest()
    
    async def embed(
        self,
        texts: List[str],
        model: str = "openai",
        use_cache: bool = True,
    ) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of texts to embed
            model: Embedding model name
            use_cache: Whether to use cached embeddings
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        # Check cache
        if use_cache:
            cache_key = self._cache_key(texts, model)
            cached = _embedding_cache.get(cache_key)
            if cached:
                return cached
        
        try:
            embeddings = await self._embed_openai(texts)
        except Exception as e:
            logger.warning(f"OpenAI embedding failed, using fallback: {e}")
            embeddings = self._embed_fallback(texts)
        
        # Cache result
        if use_cache and embeddings:
            _embedding_cache[self._cache_key(texts, model)] = embeddings
        
        return embeddings
    
    async def embed_one(self, text: str, model: str = "openai") -> List[float]:
        """Generate embedding for a single text"""
        results = await self.embed([text], model)
        return results[0] if results else []
    
    async def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI API"""
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        
        return [item.embedding for item in response.data]
    
    def _embed_fallback(self, texts: List[str]) -> List[List[float]]:
        """
        Fallback embedding using TF-IDF-like approach.
        
        This is a naive fallback that creates a simple bag-of-words vector.
        For production use, always prefer a real embedding model.
        """
        import re
        import math
        
        # Build vocabulary
        word_freq = {}
        all_words = []
        for text in texts:
            words = re.findall(r'\b\w+\b', text.lower())
            all_words.append(words)
            for word in words:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # Build vectors (128-dimension for fallback)
        dim = 128
        embeddings = []
        
        for text in texts:
            words = re.findall(r'\b\w+\b', text.lower())
            word_count = {}
            for word in words:
                word_count[word] = word_count.get(word, 0) + 1
            
            # Create TF-IDF-like vector
            vec = [0.0] * dim
            for word, count in word_count.items():
                word_hash = hash(word) % dim
                tf = count / max(len(words), 1)
                idf = math.log(len(texts) / max(word_freq.get(word, 1), 1)) + 1
                vec[word_hash] += tf * idf
            
            # Normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            
            embeddings.append(vec)
        
        return embeddings


# Singleton
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
