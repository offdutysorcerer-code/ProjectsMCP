from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class BrowserService:
    """Async Playwright wrapper for Browser plugin tools."""

    def __init__(self, artifacts_dir: Path) -> None:
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

    async def _ensure_playwright(self) -> Any:
        if self._playwright is not None:
            return self._playwright
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: uv run --with-requirements requirements.txt python -m playwright install chromium"
            ) from exc
        self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_page(self, headless: bool = False) -> Any:
        if self._page is not None and not self._page.is_closed():
            return self._page
        playwright = await self._ensure_playwright()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await playwright.chromium.launch(headless=headless)
        if self._context is None:
            self._context = await self._browser.new_context(viewport={"width": 1280, "height": 900})
        self._page = await self._context.new_page()
        return self._page

    async def _page_summary(self, page: Any) -> dict[str, Any]:
        return {
            "url": page.url,
            "title": await page.title(),
        }

    async def status(self) -> dict[str, Any]:
        page_ready = self._page is not None and not self._page.is_closed()
        return {
            "running": page_ready,
            "url": self._page.url if page_ready else None,
            "title": await self._page.title() if page_ready else None,
            "artifacts_dir": str(self.artifacts_dir),
        }

    async def open(self, url: str, headless: bool = False) -> dict[str, Any]:
        page = await self._ensure_page(headless=headless)
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        return {"status": "opened", **await self._page_summary(page)}

    async def goto(self, url: str) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.goto(url, wait_until="domcontentloaded")
        return {"status": "navigated", **await self._page_summary(page)}

    async def back(self) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.go_back(wait_until="domcontentloaded")
        return {"status": "back", **await self._page_summary(page)}

    async def text(self, max_chars: int = 12000) -> dict[str, Any]:
        page = await self._ensure_page()
        body_text = await page.locator("body").inner_text(timeout=5000)
        if len(body_text) > max_chars:
            body_text = body_text[:max_chars]
            truncated = True
        else:
            truncated = False
        return {"status": "ok", "text": body_text, "truncated": truncated, **await self._page_summary(page)}

    async def click_text(self, text: str, exact: bool = False) -> dict[str, Any]:
        page = await self._ensure_page()
        locator = page.get_by_text(text, exact=exact).first
        await locator.click(timeout=8000)
        return {"status": "clicked", "text": text, **await self._page_summary(page)}

    async def fill(self, selector: str, value: str) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.locator(selector).first.fill(value, timeout=8000)
        return {"status": "filled", "selector": selector, **await self._page_summary(page)}

    async def press(self, key: str) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.keyboard.press(key)
        return {"status": "pressed", "key": key, **await self._page_summary(page)}

    async def screenshot(self, full_page: bool = True) -> dict[str, Any]:
        page = await self._ensure_page()
        parsed = urlparse(page.url)
        host = re.sub(r"[^a-zA-Z0-9_-]+", "_", parsed.netloc or "page").strip("_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = self.artifacts_dir / f"browser_{host}_{timestamp}.png"
        await page.screenshot(path=str(path), full_page=full_page)
        return {"status": "saved", "path": str(path), **await self._page_summary(page)}

    async def close(self) -> dict[str, Any]:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        return {"status": "closed"}
