"""
Crawl4AI Service - Core Service Implementation
"""
import asyncio
import logging
import hashlib
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from cachetools import TTLCache
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Global cache for crawled content
_crawl_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)

# In-memory task storage for async tasks
_async_tasks: Dict[str, Dict[str, Any]] = {}


class Crawl4AIService:
    """
    Crawl4AI Service for LLM-friendly web content extraction.
    
    Features:
    - LLM-friendly Markdown generation
    - Multiple crawl strategies (BFS, DFS, Best-First, Smart)
    - CSS selector extraction
    - JavaScript rendering support
    - Result caching
    """
    
    def __init__(self):
        self._initialized = False
        self._crawler = None
        
    async def initialize(self) -> None:
        """Initialize the crawl4ai crawler"""
        if self._initialized:
            return
            
        try:
            from crawl4ai import AsyncWebCrawler
            
            self._crawler = AsyncWebCrawler()
            await self._crawler.__aenter__()
            self._initialized = True
            logger.info("Crawl4AI service initialized successfully")
        except ImportError:
            logger.warning("crawl4ai not installed, using fallback crawler")
            self._initialized = True  # Mark as initialized to prevent retries
        except Exception as e:
            logger.error(f"Failed to initialize crawl4ai: {e}")
            self._initialized = True  # Mark as initialized anyway
    
    async def close(self) -> None:
        """Close the crawler and cleanup resources"""
        if self._crawler:
            try:
                await self._crawler.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing crawler: {e}")
            self._initialized = False
    
    def _get_cache_key(self, url: str, css_selector: Optional[str] = None) -> str:
        """Generate cache key for URL"""
        key_str = f"{url}:{css_selector or ''}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached_result(self, url: str, css_selector: Optional[str] = None) -> Optional[Dict]:
        """Get cached crawl result"""
        cache_key = self._get_cache_key(url, css_selector)
        return _crawl_cache.get(cache_key)
    
    def _cache_result(self, url: str, css_selector: Optional[str], result: Dict, ttl: int = 3600) -> None:
        """Cache crawl result"""
        cache_key = self._get_cache_key(url, css_selector)
        _crawl_cache[cache_key] = result
    
    async def crawl(
        self,
        url: str,
        css_selector: Optional[str] = None,
        js_timeout: int = 30,
        use_cache: bool = True,
        cache_ttl: int = 3600,
    ) -> Dict[str, Any]:
        """
        Crawl a single URL and return LLM-friendly Markdown content.
        
        Args:
            url: Target URL to crawl
            css_selector: CSS selector for content extraction
            js_timeout: JavaScript render timeout in seconds
            use_cache: Whether to use cached results
            cache_ttl: Cache TTL in seconds
            
        Returns:
            Dict containing markdown, metadata, and other crawl results
        """
        # Check cache first
        if use_cache:
            cached = self._get_cached_result(url, css_selector)
            if cached:
                logger.debug(f"Cache hit for {url}")
                return cached
        
        start_time = time.time()
        
        try:
            # Try crawl4ai first
            result = await self._crawl_with_crawl4ai(
                url, css_selector, js_timeout
            )
        except Exception as e:
            logger.warning(f"crawl4ai failed, using fallback: {e}")
            result = await self._crawl_fallback(url, css_selector, js_timeout)
        
        # Calculate metadata
        crawl_time_ms = int((time.time() - start_time) * 1000)
        
        # Build response
        response = {
            "url": url,
            "markdown": result.get("markdown", ""),
            "html": result.get("html"),
            "metadata": {
                "title": result.get("title"),
                "description": result.get("description"),
                "crawl_time_ms": crawl_time_ms,
                "word_count": len(result.get("markdown", "").split()),
                "links_count": len(result.get("links", [])),
                "images_count": len(result.get("images", [])),
            },
            "links": result.get("links", []),
            "images": result.get("images", []),
        }
        
        # Cache result
        if use_cache:
            self._cache_result(url, css_selector, response, cache_ttl)
        
        return response
    
    async def _crawl_with_crawl4ai(
        self,
        url: str,
        css_selector: Optional[str] = None,
        js_timeout: int = 30,
    ) -> Dict[str, Any]:
        """Crawl using crawl4ai library"""
        if not self._initialized:
            await self.initialize()
        
        if self._crawler is None:
            raise RuntimeError("Crawl4AI crawler not available")
        
        # Configure browser
        from crawl4ai import BrowserConfig, CrawlerRunConfig
        
        browser_config = BrowserConfig(
            headless=True,
            timeout=js_timeout * 1000,
        )
        
        # Configure crawl
        run_config = CrawlerRunConfig(
            css_selector=css_selector,
            markdown_generator="fit",  # LLM-friendly Markdown
            bypass_cache=True,
            page_timeout=js_timeout * 1000,
        )
        
        # Execute crawl
        result = await self._crawler.arun(url=url, config=run_config)
        
        if result.success:
            return {
                "markdown": result.markdown,
                "html": result.html,
                "title": result.metadata.get("title") if result.metadata else None,
                "description": result.metadata.get("description") if result.metadata else None,
                "links": [
                    {"href": link.get("href", ""), "text": link.get("text", "")}
                    for link in (result.links or [])
                ],
                "images": [
                    {"src": img.get("src", ""), "alt": img.get("alt", "")}
                    for img in (result.images or [])
                ],
            }
        else:
            raise RuntimeError(f"Crawl failed: {result.error}")
    
    async def _crawl_fallback(
        self,
        url: str,
        css_selector: Optional[str] = None,
        js_timeout: int = 30,
    ) -> Dict[str, Any]:
        """Fallback crawler using httpx and basic HTML parsing"""
        import httpx
        from bs4 import BeautifulSoup
        
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgentHub/1.0; +https://agenthub.ai)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        async with httpx.AsyncClient(timeout=js_timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract content
            if css_selector:
                content = soup.select_one(css_selector)
                if content:
                    soup = content
            
            # Get title and description
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else None
            
            meta_desc = soup.find("meta", attrs={"name": "description"})
            description = meta_desc.get("content", "").strip() if meta_desc else None
            
            # Remove script and style tags
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            
            # Convert to text
            markdown = self._html_to_markdown(str(soup))
            
            # Extract links
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith(("http://", "https://")):
                    links.append({
                        "href": href,
                        "text": a.get_text(strip=True)[:100],
                    })
            
            # Extract images
            images = []
            for img in soup.find_all("img", src=True):
                images.append({
                    "src": img["src"],
                    "alt": img.get("alt", "")[:100],
                })
            
            return {
                "markdown": markdown,
                "html": html[:10000],  # Truncate HTML
                "title": title,
                "description": description,
                "links": links[:50],  # Limit links
                "images": images[:20],  # Limit images
            }
    
    def _html_to_markdown(self, html: str) -> str:
        """Simple HTML to Markdown conversion"""
        import re
        
        # Basic replacements
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'</div>', '\n', text)
        text = re.sub(r'</h[1-6]>', '\n\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()
        
        return text
    
    # ─────────────────────────────────────────────────────────────────────────
    # Async Task Management
    # ─────────────────────────────────────────────────────────────────────────
    
    def create_async_task(
        self,
        task_id: str,
        url: str,
        strategy: str = "smart",
        max_depth: int = 2,
        max_pages: int = 10,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create an async crawl task"""
        _async_tasks[task_id] = {
            "task_id": task_id,
            "url": url,
            "strategy": strategy,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "progress": 0,
            "result": None,
            "error": None,
            "kwargs": kwargs,
        }
        return _async_tasks[task_id]
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get async task status"""
        return _async_tasks.get(task_id)
    
    def update_task_status(
        self,
        task_id: str,
        status: str,
        progress: int = 0,
        result: Optional[List] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update async task status"""
        if task_id in _async_tasks:
            _async_tasks[task_id]["status"] = status
            _async_tasks[task_id]["progress"] = progress
            _async_tasks[task_id]["updated_at"] = datetime.utcnow()
            if result is not None:
                _async_tasks[task_id]["result"] = result
            if error:
                _async_tasks[task_id]["error"] = error
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel an async crawl task"""
        if task_id in _async_tasks:
            _async_tasks[task_id]["status"] = "cancelled"
            _async_tasks[task_id]["updated_at"] = datetime.utcnow()
            return True
        return False
    
    async def deep_crawl(
        self,
        url: str,
        strategy: str = "bfs",
        max_depth: int = 3,
        max_pages: int = 50,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Deep crawl with multiple pages.
        
        Args:
            url: Starting URL
            strategy: Crawl strategy (bfs, dfs, best_first)
            max_depth: Maximum crawl depth
            max_pages: Maximum pages to crawl
            
        Returns:
            Dict containing all crawled pages
        """
        from crawl4ai import BrowserConfig, CrawlerRunConfig, BFSDeepCrawlStrategy
        
        start_time = time.time()
        results = []
        
        try:
            # Configure strategy
            if strategy == "bfs":
                crawl_strategy = BFSDeepCrawlStrategy(
                    max_depth=max_depth,
                    max_pages=max_pages,
                )
            else:
                # Default to BFS for other strategies
                crawl_strategy = BFSDeepCrawlStrategy(
                    max_depth=max_depth,
                    max_pages=max_pages,
                )
            
            browser_config = BrowserConfig(headless=True)
            run_config = CrawlerRunConfig(
                deep_crawl_strategy=crawl_strategy,
                markdown_generator="fit",
            )
            
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)
                
                if result.success:
                    # Process results
                    for page in result.cleaned_data or []:
                        results.append({
                            "url": page.get("url", ""),
                            "markdown": page.get("markdown", ""),
                            "metadata": page.get("metadata", {}),
                        })
                else:
                    raise RuntimeError(f"Deep crawl failed: {result.error}")
                    
        except ImportError:
            # Fallback: crawl single page
            single_result = await self.crawl(url, **kwargs)
            results.append(single_result)
        except Exception as e:
            logger.error(f"Deep crawl error: {e}")
            raise
        
        total_time_ms = int((time.time() - start_time) * 1000)
        
        return {
            "pages_crawled": len(results),
            "results": results,
            "total_time_ms": total_time_ms,
        }


# Singleton instance
_crawl_service: Optional[Crawl4AIService] = None


async def get_crawl4ai_service() -> Crawl4AIService:
    """Get or create the crawl4ai service singleton"""
    global _crawl_service
    if _crawl_service is None:
        _crawl_service = Crawl4AIService()
        await _crawl_service.initialize()
    return _crawl_service


async def shutdown_crawl4ai_service() -> None:
    """Shutdown the crawl4ai service"""
    global _crawl_service
    if _crawl_service:
        await _crawl_service.close()
        _crawl_service = None
