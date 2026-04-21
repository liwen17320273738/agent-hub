"""Web search tool — search the internet via DuckDuckGo or fallback."""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from ..safety import sanitize_external_content

logger = logging.getLogger(__name__)

_DDGS_API = "https://api.duckduckgo.com/"


async def web_search(params: Dict[str, Any]) -> str:
    """Search the web and return summarized results."""
    query = params.get("query", "")
    if not query:
        return "Error: 'query' parameter is required"

    max_results = min(params.get("max_results", 5), 10)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "AgentHub/2.0 (bot)"},
            )

            if resp.status_code != 200:
                return f"Search returned status {resp.status_code}"

            text = resp.text
            results = _parse_ddg_html(text, max_results)

            if not results:
                return f"No results found for: {query}"

            lines = [f"Search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. **{r['title']}**")
                if r.get("snippet"):
                    lines.append(f"   {r['snippet']}")
                if r.get("url"):
                    lines.append(f"   URL: {r['url']}")
                lines.append("")

            wrapped, _scan = sanitize_external_content(
                "\n".join(lines), source="web_search", source_url=f"ddg:{query}",
            )
            return wrapped

    except httpx.TimeoutException:
        return "Error: Search request timed out"
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return f"Error: Search failed - {e}"


def _parse_ddg_html(html: str, max_results: int) -> list:
    """Basic HTML parser for DuckDuckGo results (no BeautifulSoup dep)."""
    import re

    results = []
    blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|div|span)',
        html, re.DOTALL,
    )

    for url, title, snippet in blocks[:max_results]:
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if title:
            results.append({"title": title, "snippet": snippet, "url": url})

    return results
