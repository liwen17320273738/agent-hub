"""
Crawl4AI Service - Pydantic Models
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, HttpUrl


class CrawlStrategy(str, Enum):
    """Crawl strategy options"""
    SMART = "smart"
    BFS = "bfs"
    DFS = "dfs"
    BEST_FIRST = "best_first"


class CrawlTaskStatus(str, Enum):
    """Async crawl task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    """Synchronous crawl request"""
    url: HttpUrl = Field(..., description="Target URL to crawl")
    css_selector: Optional[str] = Field(None, description="CSS selector for content extraction")
    js_timeout: int = Field(30, description="JavaScript render timeout in seconds", ge=1, le=300)
    cache_ttl: int = Field(3600, description="Cache TTL in seconds", ge=0)
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "https://example.com/article",
                    "css_selector": "article.content",
                    "js_timeout": 30
                }
            ]
        }
    }


class AsyncCrawlRequest(BaseModel):
    """Asynchronous crawl request for long-running tasks"""
    url: HttpUrl = Field(..., description="Target URL to crawl")
    strategy: CrawlStrategy = Field(CrawlStrategy.SMART, description="Crawl strategy")
    max_depth: int = Field(2, description="Max crawl depth", ge=1, le=10)
    max_pages: int = Field(10, description="Max pages to crawl", ge=1, le=100)
    css_selector: Optional[str] = Field(None, description="CSS selector for content extraction")
    js_timeout: int = Field(30, description="JavaScript render timeout in seconds", ge=1, le=300)
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "https://example.com/",
                    "strategy": "bfs",
                    "max_depth": 3,
                    "max_pages": 50
                }
            ]
        }
    }


class DeepCrawlRequest(BaseModel):
    """Deep crawl request with multiple strategies"""
    url: HttpUrl = Field(..., description="Starting URL for deep crawl")
    strategy: CrawlStrategy = Field(CrawlStrategy.BFS, description="Crawl strategy")
    max_depth: int = Field(3, description="Max crawl depth", ge=1, le=10)
    max_pages: int = Field(50, description="Max pages to crawl", ge=1, le=500)
    css_selector: Optional[str] = Field(None, description="CSS selector for content extraction")
    headless: bool = Field(True, description="Run browser in headless mode")
    user_agent: Optional[str] = Field(None, description="Custom user agent string")
    proxy: Optional[str] = Field(None, description="Proxy URL")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "https://docs.example.com/",
                    "strategy": "best_first",
                    "max_depth": 5,
                    "max_pages": 100
                }
            ]
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Response Models
# ─────────────────────────────────────────────────────────────────────────────

class CrawlMetadata(BaseModel):
    """Metadata from crawled page"""
    title: Optional[str] = Field(None, description="Page title")
    description: Optional[str] = Field(None, description="Page meta description")
    author: Optional[str] = Field(None, description="Page author")
    publish_date: Optional[str] = Field(None, description="Publish date")
    language: Optional[str] = Field(None, description="Page language")
    crawl_time_ms: int = Field(..., description="Crawl duration in milliseconds")
    word_count: int = Field(0, description="Word count of content")
    links_count: int = Field(0, description="Number of links found")
    images_count: int = Field(0, description="Number of images found")


class CrawlResult(BaseModel):
    """Single page crawl result"""
    url: str = Field(..., description="Original URL")
    markdown: str = Field(..., description="LLM-friendly Markdown content")
    html: Optional[str] = Field(None, description="Raw HTML content")
    metadata: CrawlMetadata = Field(..., description="Page metadata")
    links: List[Dict[str, str]] = Field(default_factory=list, description="Extracted links")
    images: List[Dict[str, str]] = Field(default_factory=list, description="Extracted images")


class CrawlResponse(BaseModel):
    """Synchronous crawl response"""
    success: bool = Field(True, description="Whether crawl succeeded")
    data: Optional[CrawlResult] = Field(None, description="Crawl result data")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "data": {
                        "url": "https://example.com/article",
                        "markdown": "# Article Title\n\n文章内容...",
                        "metadata": {
                            "title": "页面标题",
                            "crawl_time_ms": 1523,
                            "word_count": 2048
                        }
                    }
                }
            ]
        }
    }


class AsyncCrawlResponse(BaseModel):
    """Async crawl task creation response"""
    success: bool = Field(True, description="Whether task creation succeeded")
    task_id: str = Field(..., description="Unique task identifier")
    status: CrawlTaskStatus = Field(CrawlTaskStatus.PENDING, description="Initial task status")
    message: Optional[str] = Field(None, description="Status message")


class CrawlTask(BaseModel):
    """Async crawl task details"""
    task_id: str = Field(..., description="Unique task identifier")
    url: str = Field(..., description="Target URL")
    status: CrawlTaskStatus = Field(..., description="Current task status")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Task creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    progress: int = Field(0, description="Progress percentage (0-100)")
    result: Optional[List[CrawlResult]] = Field(None, description="Crawl results if completed")
    error: Optional[str] = Field(None, description="Error message if failed")


class CrawlTaskStatusResponse(BaseModel):
    """Async crawl task status response"""
    success: bool = Field(True, description="Whether query succeeded")
    task: Optional[CrawlTask] = Field(None, description="Task details")


class DeepCrawlResponse(BaseModel):
    """Deep crawl response with multiple pages"""
    success: bool = Field(True, description="Whether crawl succeeded")
    task_id: str = Field(..., description="Unique task identifier")
    status: CrawlTaskStatus = Field(..., description="Task status")
    pages_crawled: int = Field(0, description="Number of pages crawled")
    results: Optional[List[CrawlResult]] = Field(None, description="All crawled pages")
    total_time_ms: int = Field(0, description="Total crawl duration in milliseconds")
    error: Optional[str] = Field(None, description="Error message if failed")
