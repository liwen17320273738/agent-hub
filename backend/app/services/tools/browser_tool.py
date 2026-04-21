"""Browser tool — headless Playwright agent for web research / E2E testing.

Soft-imports playwright.async_api; if missing, all functions return a
clear "not installed" message and the registry can register the tools
as no-ops without crashing.

Stateless API for v1: every call opens a fresh browser context, performs
the action, and closes. This trades latency for simplicity and isolation.

Tools exposed:
- browser_open       → fetch a URL and return rendered text + title + status
- browser_screenshot → capture page as PNG (returned as base64 data URL)
- browser_extract    → fetch URL + extract via CSS selector
- browser_click_flow → goto → click → extract; covers SPA navigation
- browser_search     → DuckDuckGo Lite via headless browser (rendered)

Future v2: persistent contexts per task, login session reuse, full agent loop.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional

from ...config import settings
from ..safety import sanitize_external_content

logger = logging.getLogger(__name__)


def _playwright_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


async def _new_context(headless: bool = True):
    """Lazy import; returns (playwright, browser, context) tuple, or None."""
    if not _playwright_available():
        return None
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 AgentHub-Browser/1.0"
        ),
    )
    context.set_default_timeout(settings.browser_default_timeout_ms)
    return pw, browser, context


async def _close(triple) -> None:
    if not triple:
        return
    pw, browser, context = triple
    try:
        await context.close()
    except Exception:
        pass
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await pw.stop()
    except Exception:
        pass


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text) - limit} chars omitted]"


async def browser_open(params: Dict[str, Any]) -> str:
    """Goto a URL and return title + rendered text content (truncated)."""
    if not _playwright_available():
        return "Error: Playwright is not installed. Run: pip install playwright && playwright install chromium"
    url = (params.get("url") or "").strip()
    if not url:
        return "Error: 'url' is required"
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Error: url must start with http:// or https://"
    wait_for = params.get("wait_for") or "networkidle"
    text_limit = int(params.get("text_limit") or 8000)

    triple = await _new_context()
    try:
        _, _, context = triple
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until=wait_for, timeout=settings.browser_default_timeout_ms)
        except Exception as e:
            return f"Error navigating to {url}: {e}"
        status = response.status if response else 0
        title = await page.title()
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        body, _scan = sanitize_external_content(
            text or "", source="browser_open", source_url=url, max_chars=text_limit,
        )
        return f"[browser_open] status={status} title={title!r}\n\n{body}"
    finally:
        await _close(triple)


async def browser_screenshot(params: Dict[str, Any]) -> str:
    """Capture a screenshot; returns base64 data URL (PNG)."""
    if not _playwright_available():
        return "Error: Playwright is not installed. Run: pip install playwright && playwright install chromium"
    url = (params.get("url") or "").strip()
    if not url:
        return "Error: 'url' is required"
    full_page = bool(params.get("full_page", True))

    triple = await _new_context()
    try:
        _, _, context = triple
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle")
        except Exception as e:
            return f"Error navigating: {e}"
        png = await page.screenshot(full_page=full_page, type="png")
        encoded = base64.b64encode(png).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    finally:
        await _close(triple)


async def browser_extract(params: Dict[str, Any]) -> str:
    """Goto URL, return text content of all elements matching CSS selector."""
    if not _playwright_available():
        return "Error: Playwright is not installed."
    url = (params.get("url") or "").strip()
    selector = (params.get("selector") or "").strip()
    if not url or not selector:
        return "Error: both 'url' and 'selector' are required"
    limit = int(params.get("limit") or 30)

    triple = await _new_context()
    try:
        _, _, context = triple
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")
        try:
            await page.wait_for_selector(selector, timeout=10000)
        except Exception:
            return f"[browser_extract] selector {selector!r} not found within 10s"
        elements = await page.query_selector_all(selector)
        results: List[str] = []
        for el in elements[:limit]:
            try:
                txt = (await el.inner_text()) or ""
            except Exception:
                txt = ""
            txt = txt.strip()
            if txt:
                results.append(txt)
        body, _scan = sanitize_external_content(
            "\n---\n".join(results), source="browser_extract", source_url=url,
        )
        return (
            f"[browser_extract] selector={selector} "
            f"matched={len(elements)} returned={len(results)}\n\n{body}"
        )
    finally:
        await _close(triple)


async def browser_click_flow(params: Dict[str, Any]) -> str:
    """Goto → click selector → wait → return new page text. For SPA navigation."""
    if not _playwright_available():
        return "Error: Playwright is not installed."
    url = (params.get("url") or "").strip()
    click_selector = (params.get("click_selector") or "").strip()
    if not url or not click_selector:
        return "Error: 'url' and 'click_selector' are required"
    extract_selector: Optional[str] = params.get("extract_selector")
    text_limit = int(params.get("text_limit") or 6000)

    triple = await _new_context()
    try:
        _, _, context = triple
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")
        try:
            await page.click(click_selector, timeout=10000)
        except Exception as e:
            return f"Error clicking {click_selector!r}: {e}"
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await asyncio.sleep(1)
        if extract_selector:
            try:
                el = await page.wait_for_selector(extract_selector, timeout=8000)
                txt = (await el.inner_text()) if el else ""
                wrapped, _scan = sanitize_external_content(
                    txt or "", source="browser_click_flow",
                    source_url=page.url, max_chars=text_limit,
                )
                return f"[browser_click_flow] post-click selector={extract_selector}\n\n{wrapped}"
            except Exception as e:
                return f"[browser_click_flow] click ok, but extract selector {extract_selector!r} failed: {e}"
        body = await page.evaluate("() => document.body ? document.body.innerText : ''")
        wrapped, _scan = sanitize_external_content(
            body or "", source="browser_click_flow",
            source_url=page.url, max_chars=text_limit,
        )
        return f"[browser_click_flow] post-click url={page.url}\n\n{wrapped}"
    finally:
        await _close(triple)
