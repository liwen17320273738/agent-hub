"""
Crawl4AI Service - LLM-friendly web crawler integration
"""
from .service import Crawl4AIService, get_crawl4ai_service
from .models import (
    CrawlRequest,
    CrawlResponse,
    AsyncCrawlRequest,
    AsyncCrawlResponse,
    DeepCrawlRequest,
    CrawlTaskStatus,
)

__all__ = [
    "Crawl4AIService",
    "get_crawl4ai_service",
    "CrawlRequest",
    "CrawlResponse",
    "AsyncCrawlRequest",
    "AsyncCrawlResponse",
    "DeepCrawlRequest",
    "CrawlTaskStatus",
]
