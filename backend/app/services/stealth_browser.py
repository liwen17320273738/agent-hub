"""
Anti-Bot Browser Automation - Real browser with stealth capabilities.

Integrates Playwright with anti-detection measures for E2E testing.
"""
import logging
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class StealthBrowser:
    """
    Anti-bot stealth browser for E2E testing and web automation.
    
    Features:
    - Real Chromium browser control
    - Anti-bot detection evasion
    - Cookie/session import/export
    - Screenshot and video recording
    - Natural interaction simulation
    """
    
    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._stealth_mode = True
    
    async def open(
        self,
        headless: bool = True,
        stealth: bool = True,
        viewport: str = "1280x720",
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone: str = "America/New_York",
    ) -> Dict[str, Any]:
        """
        Open a stealth browser instance.
        
        Args:
            headless: Run in headless mode
            stealth: Enable anti-bot stealth
            viewport: Viewport size (WxH)
            user_agent: Custom user agent
            locale: Browser locale
            timezone: Browser timezone
            
        Returns:
            Dict with browser info
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"success": False, "error": "playwright not installed. Run: pip install playwright && playwright install chromium"}
        
        self._stealth_mode = stealth
        width, height = map(int, viewport.split("x"))
        
        pw = await async_playwright().start()
        # Retain the driver so close() can stop it — otherwise the playwright
        # node driver (and the chromium it manages) leaks as a zombie process.
        self._playwright = pw
        
        # Stealth launch args
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
        ]
        
        if stealth:
            launch_args.extend([
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-component-extensions-with-background-pages",
            ])
        
        self._browser = await pw.chromium.launch(
            headless=headless,
            args=launch_args,
        )
        
        # Create context with anti-detection
        context_options = {
            "viewport": {"width": width, "height": height},
            "locale": locale,
            "timezone_id": timezone,
        }
        
        if user_agent:
            context_options["user_agent"] = user_agent
        elif stealth:
            # Use a common non-bot user agent
            context_options["user_agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        
        self._context = await self._browser.new_context(**context_options)
        
        # Apply stealth scripts
        if stealth:
            await self._context.add_init_script("""
                // Override navigator properties
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                
                // Override chrome runtime
                window.chrome = { runtime: {} };
                
                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({state: 'prompt', onchange: null}) :
                    originalQuery(parameters)
                );
            """)
        
        self._page = await self._context.new_page()
        
        logger.info(f"Stealth browser opened (headless={headless}, stealth={stealth})")
        
        return {
            "success": True,
            "headless": headless,
            "stealth": stealth,
            "viewport": viewport,
            "user_agent": user_agent or "default",
        }
    
    async def navigate(self, url: str, wait_until: str = "networkidle") -> Dict[str, Any]:
        """Navigate to a URL"""
        if not self._page:
            return {"success": False, "error": "Browser not open"}
        
        try:
            response = await self._page.goto(url, wait_until=wait_until, timeout=30000)
            title = await self._page.title()
            content = await self._page.content()
            
            return {
                "success": True,
                "url": url,
                "status": response.status if response else 0,
                "title": title,
                "content_length": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def screenshot(self, path: Optional[str] = None, full_page: bool = True) -> str:
        """Take a screenshot"""
        if not self._page:
            raise RuntimeError("Browser not open")
        
        if not path:
            path = f"screenshots/screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
        
        await self._page.screenshot(path=path, full_page=full_page)
        return path
    
    async def click(
        self,
        selector: str,
        timeout: int = 5000,
    ) -> Dict[str, Any]:
        """Click an element with natural delay simulation"""
        if not self._page:
            return {"success": False, "error": "Browser not open"}
        
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if not element:
                return {"success": False, "error": f"Element not found: {selector}"}
            
            # Natural interaction: scroll into view, slight delay
            await element.scroll_into_view_if_needed()
            await asyncio.sleep(0.1)
            await element.click()
            
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def fill(
        self,
        selector: str,
        value: str,
        timeout: int = 5000,
    ) -> Dict[str, Any]:
        """Fill an input field with human-like typing simulation"""
        if not self._page:
            return {"success": False, "error": "Browser not open"}
        
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if not element:
                return {"success": False, "error": f"Element not found: {selector}"}
            
            await element.fill("")
            
            if self._stealth_mode:
                # Type character by character with slight delays
                for char in value:
                    await element.type(char, delay=30)  # 30ms delay per character
            else:
                await element.fill(value)
            
            return {"success": True, "selector": selector, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def extract_text(self, selector: str) -> str:
        """Extract text from an element"""
        if not self._page:
            return ""
        
        try:
            element = await self._page.wait_for_selector(selector)
            return await element.inner_text() if element else ""
        except Exception:
            return ""
    
    async def extract_all_text(self) -> str:
        """Extract all visible text from the page"""
        if not self._page:
            return ""
        return await self._page.inner_text("body")
    
    async def execute_javascript(self, code: str) -> Any:
        """Execute JavaScript in the page context"""
        if not self._page:
            return None
        return await self._page.evaluate(code)
    
    async def wait_for(
        self,
        selector: Optional[str] = None,
        timeout: int = 10000,
    ) -> Dict[str, Any]:
        """Wait for a selector or timeout"""
        if not self._page:
            return {"success": False, "error": "Browser not open"}
        
        if selector:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            return {"success": element is not None, "found": element is not None}
        
        await asyncio.sleep(timeout / 1000)
        return {"success": True}
    
    async def get_cookies(self) -> List[Dict]:
        """Export browser cookies"""
        if not self._context:
            return []
        return await self._context.cookies()
    
    async def set_cookies(self, cookies: List[Dict]) -> None:
        """Import cookies to browser context"""
        if self._context:
            await self._context.add_cookies(cookies)
    
    async def close(self) -> None:
        """Close the browser and stop the underlying playwright driver.

        Both steps run independently so that a failure closing the browser
        still stops the driver — leaving the driver running is what leaks
        zombie chromium processes after preview/qa runs.
        """
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("Stealth browser close failed: %s", e)
            self._browser = None
            self._context = None
            self._page = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning("Playwright driver stop failed: %s", e)
            self._playwright = None
        logger.info("Stealth browser closed")


# Singleton
_stealth_browser: Optional[StealthBrowser] = None


def get_stealth_browser() -> StealthBrowser:
    """Get or create the stealth browser singleton"""
    global _stealth_browser
    if _stealth_browser is None:
        _stealth_browser = StealthBrowser()
    return _stealth_browser
