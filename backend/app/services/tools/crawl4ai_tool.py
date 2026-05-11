"""
Crawl4AI Tool - Agent Tool Implementation

This tool enables AI agents to crawl web pages and extract LLM-friendly content.
"""
import logging
from typing import Dict, Any, Optional

from ..crawl.service import get_crawl4ai_service

logger = logging.getLogger(__name__)


async def crawl4ai_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute crawl4ai tool.
    
    Args:
        params: Tool parameters
            - url (str, required): Target URL to crawl
            - strategy (str, optional): Crawl strategy [bfs|dfs|best_first|smart]
            - max_depth (int, optional): Max crawl depth (default: 2)
            - max_pages (int, optional): Max pages to crawl (default: 10)
            - css_selector (str, optional): CSS selector for content extraction
            - js_timeout (int, optional): JavaScript render timeout (default: 30)
            
    Returns:
        Dict with execution result
    """
    url = params.get("url")
    if not url:
        return {
            "success": False,
            "error": "URL is required",
        }
    
    try:
        service = await get_crawl4ai_service()
        
        result = await service.crawl(
            url=url,
            css_selector=params.get("css_selector"),
            js_timeout=params.get("js_timeout", 30),
        )
        
        # Return structured result for agent consumption
        return {
            "success": True,
            "url": result["url"],
            "markdown": result["markdown"],
            "metadata": {
                "title": result["metadata"].get("title"),
                "word_count": result["metadata"].get("word_count", 0),
                "crawl_time_ms": result["metadata"].get("crawl_time_ms", 0),
            },
            "summary": _generate_summary(result["markdown"], result["metadata"]),
        }
    except Exception as e:
        logger.error(f"crawl4ai execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def crawl4ai_batch_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute batch crawl4ai tool for multiple URLs.
    
    Args:
        params: Tool parameters
            - urls (list[str], required): List of URLs to crawl
            - css_selector (str, optional): CSS selector for content extraction
            - js_timeout (int, optional): JavaScript render timeout (default: 30)
            
    Returns:
        Dict with batch execution results
    """
    urls = params.get("urls", [])
    if not urls:
        return {
            "success": False,
            "error": "URLs list is required",
        }
    
    if len(urls) > 20:
        return {
            "success": False,
            "error": "Maximum 20 URLs allowed per batch",
        }
    
    try:
        service = await get_crawl4ai_service()
        results = []
        
        for url in urls:
            try:
                result = await service.crawl(
                    url=url,
                    css_selector=params.get("css_selector"),
                    js_timeout=params.get("js_timeout", 30),
                )
                results.append({
                    "success": True,
                    "url": url,
                    "markdown": result["markdown"],
                    "word_count": result["metadata"].get("word_count", 0),
                })
            except Exception as e:
                results.append({
                    "success": False,
                    "url": url,
                    "error": str(e),
                })
        
        successful = sum(1 for r in results if r.get("success"))
        
        return {
            "success": successful > 0,
            "total": len(urls),
            "completed": successful,
            "failed": len(urls) - successful,
            "results": results,
        }
    except Exception as e:
        logger.error(f"crawl4ai batch execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def crawl4ai_deep_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute deep crawl4ai for exploring multiple pages.
    
    Args:
        params: Tool parameters
            - url (str, required): Starting URL
            - strategy (str, optional): Crawl strategy (default: bfs)
            - max_depth (int, optional): Max depth (default: 3)
            - max_pages (int, optional): Max pages (default: 50)
            
    Returns:
        Dict with deep crawl results
    """
    url = params.get("url")
    if not url:
        return {
            "success": False,
            "error": "URL is required",
        }
    
    try:
        service = await get_crawl4ai_service()
        
        result = await service.deep_crawl(
            url=url,
            strategy=params.get("strategy", "bfs"),
            max_depth=params.get("max_depth", 3),
            max_pages=params.get("max_pages", 50),
        )
        
        # Generate summary of all pages
        summaries = []
        for page in result.get("results", [])[:10]:  # Top 10 pages
            summaries.append({
                "url": page.get("url", ""),
                "summary": _generate_summary(
                    page.get("markdown", ""),
                    {"word_count": len(page.get("markdown", "").split())}
                ),
            })
        
        return {
            "success": True,
            "pages_crawled": result.get("pages_crawled", 0),
            "total_time_ms": result.get("total_time_ms", 0),
            "summaries": summaries,
            "all_results": result.get("results", []),
        }
    except Exception as e:
        logger.error(f"crawl4ai deep execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def _generate_summary(markdown: str, metadata: Dict[str, Any]) -> str:
    """Generate a brief summary of the crawled content."""
    if not markdown:
        return "No content available"
    
    # Take first 500 chars as summary
    summary = markdown[:500]
    
    # Try to get a better summary point
    lines = markdown.split("\n")
    for line in lines:
        if line.startswith("# ") and len(line) > 10:
            summary = line
            break
    
    word_count = metadata.get("word_count", 0)
    if word_count:
        summary += f"\n\n[Total: {word_count} words]"
    
    return summary


# Tool schema for registry
CRAWL4AI_TOOL_SCHEMA = {
    "name": "crawl4ai",
    "description": "Crawl a URL and return LLM-friendly Markdown content. Use this when you need to gather information from web pages for research, analysis, or context gathering.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Target URL to crawl",
            },
            "strategy": {
                "type": "string",
                "description": "Crawl strategy: bfs (breadth-first), dfs (depth-first), best_first, smart (default)",
                "enum": ["bfs", "dfs", "best_first", "smart"],
                "default": "smart",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum crawl depth for deep crawling",
                "minimum": 1,
                "maximum": 10,
                "default": 2,
            },
            "max_pages": {
                "type": "integer",
                "description": "Maximum number of pages to crawl in deep mode",
                "minimum": 1,
                "maximum": 100,
                "default": 10,
            },
            "css_selector": {
                "type": "string",
                "description": "CSS selector for extracting specific content (e.g., 'article.content', '.main-text')",
            },
            "js_timeout": {
                "type": "integer",
                "description": "JavaScript render timeout in seconds",
                "minimum": 1,
                "maximum": 300,
                "default": 30,
            },
        },
        "required": ["url"],
    },
}


CRAWL4AI_BATCH_TOOL_SCHEMA = {
    "name": "crawl4ai_batch",
    "description": "Crawl multiple URLs in batch and return LLM-friendly Markdown content for each.",
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of URLs to crawl (max 20)",
                "maxItems": 20,
            },
            "css_selector": {
                "type": "string",
                "description": "CSS selector for extracting specific content",
            },
            "js_timeout": {
                "type": "integer",
                "description": "JavaScript render timeout in seconds",
                "default": 30,
            },
        },
        "required": ["urls"],
    },
}


CRAWL4AI_DEEP_TOOL_SCHEMA = {
    "name": "crawl4ai_deep",
    "description": "Deep crawl multiple pages from a starting URL using BFS/DFS strategies.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Starting URL for deep crawl",
            },
            "strategy": {
                "type": "string",
                "description": "Crawl strategy: bfs (recommended), dfs, best_first",
                "enum": ["bfs", "dfs", "best_first"],
                "default": "bfs",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum crawl depth",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
            },
            "max_pages": {
                "type": "integer",
                "description": "Maximum pages to crawl",
                "minimum": 1,
                "maximum": 500,
                "default": 50,
            },
        },
        "required": ["url"],
    },
}
