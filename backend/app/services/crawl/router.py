"""
Crawl4AI Service - FastAPI Router
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks

from .models import (
    CrawlRequest,
    CrawlResponse,
    AsyncCrawlRequest,
    AsyncCrawlResponse,
    DeepCrawlRequest,
    DeepCrawlResponse,
    CrawlTaskStatusResponse,
    CrawlTask,
    CrawlResult,
    CrawlTaskStatus,
    CrawlMetadata,
)
from .service import get_crawl4ai_service


router = APIRouter(prefix="/api/v1/crawl", tags=["crawl"])


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=CrawlResponse)
async def crawl_url(request: CrawlRequest) -> CrawlResponse:
    """
    Synchronously crawl a single URL and return LLM-friendly Markdown.
    
    - **url**: Target URL to crawl
    - **css_selector**: Optional CSS selector for content extraction
    - **js_timeout**: JavaScript render timeout in seconds (default: 30)
    - **cache_ttl**: Cache TTL in seconds (default: 3600)
    """
    try:
        service = await get_crawl4ai_service()
        
        result = await service.crawl(
            url=str(request.url),
            css_selector=request.css_selector,
            js_timeout=request.js_timeout,
            cache_ttl=request.cache_ttl,
        )
        
        # Build response
        return CrawlResponse(
            success=True,
            data=CrawlResult(
                url=result["url"],
                markdown=result["markdown"],
                html=result.get("html"),
                metadata=CrawlMetadata(
                    title=result["metadata"].get("title"),
                    description=result["metadata"].get("description"),
                    crawl_time_ms=result["metadata"].get("crawl_time_ms", 0),
                    word_count=result["metadata"].get("word_count", 0),
                    links_count=result["metadata"].get("links_count", 0),
                    images_count=result["metadata"].get("images_count", 0),
                ),
                links=result.get("links", []),
                images=result.get("images", []),
            ),
        )
    except Exception as e:
        return CrawlResponse(
            success=False,
            error=str(e),
        )


@router.post("/sync", response_model=CrawlResponse)
async def crawl_url_sync(request: CrawlRequest) -> CrawlResponse:
    """Alias for POST /api/v1/crawl"""
    return await crawl_url(request)


# ─────────────────────────────────────────────────────────────────────────────
# Async Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/async", response_model=AsyncCrawlResponse)
async def create_async_crawl(request: AsyncCrawlRequest) -> AsyncCrawlResponse:
    """
    Create an asynchronous crawl task.
    
    Returns a task_id that can be used to query status and results.
    """
    task_id = f"crawl_{uuid.uuid4().hex[:12]}"
    
    try:
        service = await get_crawl4ai_service()
        
        # Create task
        service.create_async_task(
            task_id=task_id,
            url=str(request.url),
            strategy=request.strategy.value,
            max_depth=request.max_depth,
            max_pages=request.max_pages,
            css_selector=request.css_selector,
            js_timeout=request.js_timeout,
        )
        
        return AsyncCrawlResponse(
            success=True,
            task_id=task_id,
            status=CrawlTaskStatus.PENDING,
            message="Task created successfully. Use GET /api/v1/crawl/{task_id} to check status.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=CrawlTaskStatusResponse)
async def get_crawl_status(task_id: str) -> CrawlTaskStatusResponse:
    """
    Get the status of an asynchronous crawl task.
    
    - **task_id**: The task identifier returned from POST /api/v1/crawl/async
    """
    service = await get_crawl4ai_service()
    task = service.get_task_status(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    # Convert result if present
    result_data = None
    if task.get("result"):
        result_data = [
            CrawlResult(
                url=r["url"],
                markdown=r["markdown"],
                html=r.get("html"),
                metadata=CrawlMetadata(
                    title=r["metadata"].get("title"),
                    description=r["metadata"].get("description"),
                    crawl_time_ms=r["metadata"].get("crawl_time_ms", 0),
                    word_count=r["metadata"].get("word_count", 0),
                ),
            )
            for r in task["result"]
        ]
    
    return CrawlTaskStatusResponse(
        success=True,
        task=CrawlTask(
            task_id=task["task_id"],
            url=task["url"],
            status=CrawlTaskStatus(task["status"]),
            created_at=task["created_at"],
            updated_at=task["updated_at"],
            progress=task.get("progress", 0),
            result=result_data,
            error=task.get("error"),
        ),
    )


@router.delete("/{task_id}")
async def cancel_crawl_task(task_id: str) -> dict:
    """
    Cancel an asynchronous crawl task.
    
    - **task_id**: The task identifier to cancel
    """
    service = await get_crawl4ai_service()
    success = service.cancel_task(task_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    return {"success": True, "message": f"Task {task_id} cancelled"}


# ─────────────────────────────────────────────────────────────────────────────
# Deep Crawl Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/deep", response_model=DeepCrawlResponse)
async def deep_crawl(request: DeepCrawlRequest) -> DeepCrawlResponse:
    """
    Deep crawl multiple pages from a starting URL.
    
    - **url**: Starting URL for deep crawl
    - **strategy**: Crawl strategy (bfs, dfs, best_first)
    - **max_depth**: Maximum crawl depth (1-10)
    - **max_pages**: Maximum pages to crawl (1-500)
    """
    try:
        service = await get_crawl4ai_service()
        
        result = await service.deep_crawl(
            url=str(request.url),
            strategy=request.strategy.value,
            max_depth=request.max_depth,
            max_pages=request.max_pages,
        )
        
        # Convert results
        results = []
        for page in result.get("results", []):
            results.append(
                CrawlResult(
                    url=page.get("url", ""),
                    markdown=page.get("markdown", ""),
                    metadata=CrawlMetadata(
                        title=page.get("metadata", {}).get("title"),
                        description=page.get("metadata", {}).get("description"),
                        crawl_time_ms=page.get("metadata", {}).get("crawl_time_ms", 0),
                        word_count=len(page.get("markdown", "").split()),
                    ),
                )
            )
        
        return DeepCrawlResponse(
            success=True,
            task_id=f"deep_{uuid.uuid4().hex[:12]}",
            status=CrawlTaskStatus.COMPLETED,
            pages_crawled=result.get("pages_crawled", 0),
            results=results,
            total_time_ms=result.get("total_time_ms", 0),
        )
    except Exception as e:
        return DeepCrawlResponse(
            success=False,
            task_id="",
            status=CrawlTaskStatus.FAILED,
            error=str(e),
            pages_crawled=0,
            total_time_ms=0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Batch Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class BatchCrawlRequest(BaseModel):
    """Batch crawl request"""
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=20)
    css_selector: Optional[str] = None
    js_timeout: int = Field(30, ge=1, le=300)


class BatchCrawlResponse(BaseModel):
    """Batch crawl response"""
    success: bool
    total: int
    completed: int
    failed: int
    results: list[CrawlResponse]


from pydantic import BaseModel, Field, HttpUrl


@router.post("/batch", response_model=BatchCrawlResponse)
async def batch_crawl(request: BatchCrawlRequest) -> BatchCrawlResponse:
    """
    Crawl multiple URLs in batch.
    
    - **urls**: List of URLs to crawl (max 20)
    - **css_selector**: Optional CSS selector for all URLs
    - **js_timeout**: JavaScript render timeout in seconds
    """
    service = await get_crawl4ai_service()
    results = []
    completed = 0
    failed = 0
    
    for url in request.urls:
        try:
            result = await service.crawl(
                url=str(url),
                css_selector=request.css_selector,
                js_timeout=request.js_timeout,
            )
            
            results.append(
                CrawlResponse(
                    success=True,
                    data=CrawlResult(
                        url=result["url"],
                        markdown=result["markdown"],
                        metadata=CrawlMetadata(
                            title=result["metadata"].get("title"),
                            description=result["metadata"].get("description"),
                            crawl_time_ms=result["metadata"].get("crawl_time_ms", 0),
                            word_count=result["metadata"].get("word_count", 0),
                        ),
                    ),
                )
            )
            completed += 1
        except Exception as e:
            results.append(CrawlResponse(success=False, error=str(e)))
            failed += 1
    
    return BatchCrawlResponse(
        success=completed > 0,
        total=len(request.urls),
        completed=completed,
        failed=failed,
        results=results,
    )
