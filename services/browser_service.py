from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class BrowserService:
    """Async Playwright wrapper that attaches to a dedicated Microsoft Edge profile over CDP."""

    def __init__(self, artifacts_dir: Path) -> None:
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.profile_dir = self.artifacts_dir.parent / "browser_profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # 動態獲取 Edge 路徑
        self.edge_path = self._find_edge_path()
        self.cdp_host = "127.0.0.1"
        self.cdp_port = 9222
        self.cdp_url = f"http://{self.cdp_host}:{self.cdp_port}"

        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._edge_process: subprocess.Popen[Any] | None = None
        self._stealth_injected = False

    def _find_edge_path(self) -> Path:
        """動態查找 Microsoft Edge 可執行文件。"""
        possible_paths = [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Microsoft\\Edge\\Application\\msedge.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Microsoft\\Edge\\Application\\msedge.exe",
        ]
        for path in possible_paths:
            if path.exists():
                return path
        # 如果都找不到，返回第一個路徑以便報錯
        return possible_paths[0]

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

    async def _reset_connection(self) -> None:
        """Discard Playwright/CDP objects that may belong to a closed event loop."""
        playwright = self._playwright

        # Clear references first so a failed cleanup cannot leave stale objects reusable.
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._stealth_injected = False

        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                # A transport created by a previous request loop can no longer be stopped.
                pass

    def _start_edge(self, headless: bool = False) -> None:
        if not self.edge_path.exists():
            raise RuntimeError(f"Microsoft Edge was not found at: {self.edge_path}")

        # 1. 檢查當前執行個體是否已經啟動
        if self._edge_process is not None and self._edge_process.poll() is None:
            return

        # 2. 【新增】檢查系統中是否已有 Edge 正在運行 (復用上一次的瀏覽器)
        import urllib.request
        try:
            # 嘗試連接 CDP 端點，如果成功代表瀏覽器還在
            urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1)
            # 如果成功，代表瀏覽器已存在，我們復用它
            # 注意：這裡不啟動新進程，所以 self._edge_process 保持為 None
            # 這意味著後續的 browser_close 工具不會強行關閉這個外部進程
            return
        except Exception:
            pass # 如果連接失敗，表示沒有瀏覽器在運行，繼續執行下方的啟動邏輯

        # 3. 原有的啟動邏輯 (新增參數以隱藏自動化特徵)
        args = [
            str(self.edge_path),
            f"--remote-debugging-address={self.cdp_host}",
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",  # 【關鍵】隱藏自動化特徵
            "--disable-features=AutomationExtension",         # 【關鍵】隱藏自動化擴充功能
            "--disable-infobars",                            # 隱藏 "Chrome is being controlled by automated test software" 資訊欄
            "--disable-extensions-except=",                  # 清除所有擴充功能以避免干擾
            "--disable-gpu",                                 # 在某些環境下有助於穩定
            "--window-size=1920,1080",                       # 確保有正常的視窗大小
            "about:blank",
        ]
        if headless:
            args.insert(1, "--headless=new")

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self._edge_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )


    async def _connect_cdp(self, headless: bool = False) -> None:
        playwright = await self._ensure_playwright()
        self._start_edge(headless=headless)

        last_error: Exception | None = None
        for i in range(40):  # 增加重試次數
            try:
                # 增加連接超時時間
                self._browser = await playwright.chromium.connect_over_cdp(
                    self.cdp_url,
                    timeout=30000  # 30秒超時
                )
                # 連接成功後，等待瀏覽器完全就緒
                await asyncio.sleep(1)
                break
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.5)  # 稍微延長等待時間
        else:
            raise RuntimeError(
                f"Microsoft Edge started, but Playwright could not connect to {self.cdp_url}. "
                "Make sure port 9222 is not being used by another application."
            ) from last_error

        contexts = self._browser.contexts
        if not contexts:
            raise RuntimeError("Connected to Microsoft Edge, but no browser context was available.")
        self._context = contexts[0]

        # 【重要】在連接後立即注入隱藏腳本
        await self._inject_stealth_script()

    async def _inject_stealth_script(self) -> None:
        """注入腳本以隱藏自動化特徵。"""
        if self._stealth_injected:
            return

        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });

            // 隱藏 ChromeDriver 特徵
            window.chrome = {
                runtime: {},
            };

            // 模擬正常的 plugins 長度
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // 模擬正常的 languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-TW', 'zh', 'en-US', 'en'],
            });
        """)
        self._stealth_injected = True

    async def _ensure_page(self, headless: bool = False) -> Any:
        if self._page is not None:
            try:
                browser_connected = self._browser is not None and self._browser.is_connected()
                if browser_connected and not self._page.is_closed():
                    # is_closed() is only local state. A lightweight protocol call also
                    # verifies that the underlying Playwright transport is still alive.
                    await self._page.title()
                    return self._page
            except Exception:
                pass
            await self._reset_connection()

        if self._browser is None or not self._browser.is_connected():
            await self._connect_cdp(headless=headless)

        pages = [page for page in self._context.pages if not page.is_closed()]
        self._page = pages[0] if pages else await self._context.new_page()
        return self._page

    async def _page_summary(self, page: Any) -> dict[str, Any]:
        return {"url": page.url, "title": await page.title()}

    def _open_pages(self) -> list[Any]:
        if self._context is None:
            return []
        return [page for page in self._context.pages if not page.is_closed()]

    async def tabs(self) -> dict[str, Any]:
        await self._ensure_page()
        pages = self._open_pages()
        items: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            items.append({
                "index": index,
                "active": page is self._page,
                "url": page.url,
                "title": await page.title(),
            })
        return {"status": "ok", "count": len(items), "tabs": items}

    async def switch_tab(self, index: int) -> dict[str, Any]:
        await self._ensure_page()
        pages = self._open_pages()
        if index < 0 or index >= len(pages):
            raise ValueError(f"Tab index out of range: {index}. Available tabs: 0-{max(len(pages) - 1, 0)}")
        self._page = pages[index]
        await self._page.bring_to_front()
        return {"status": "switched", "index": index, **await self._page_summary(self._page)}

    async def new_tab(self, url: str = "") -> dict[str, Any]:
        await self._ensure_page()
        self._page = await self._context.new_page()
        if url:
            await self._page.goto(url, wait_until="domcontentloaded")
        await self._page.bring_to_front()
        pages = self._open_pages()
        return {"status": "created", "index": pages.index(self._page), **await self._page_summary(self._page)}

    async def close_tab(self, index: int | None = None) -> dict[str, Any]:
        await self._ensure_page()
        pages = self._open_pages()
        if not pages:
            return {"status": "no_tabs"}

        if index is None:
            target = self._page
            index = pages.index(target)
        else:
            if index < 0 or index >= len(pages):
                raise ValueError(f"Tab index out of range: {index}. Available tabs: 0-{len(pages) - 1}")
            target = pages[index]

        await target.close()
        remaining = self._open_pages()
        self._page = remaining[min(index, len(remaining) - 1)] if remaining else None
        if self._page is not None:
            await self._page.bring_to_front()
            return {"status": "closed", "closed_index": index, **await self._page_summary(self._page)}
        return {"status": "closed", "closed_index": index, "url": None, "title": None}

    async def activate_tab(self, query: str) -> dict[str, Any]:
        await self._ensure_page()
        needle = query.casefold()
        pages = self._open_pages()
        for index, page in enumerate(pages):
            title = await page.title()
            if needle in title.casefold() or needle in page.url.casefold():
                self._page = page
                await page.bring_to_front()
                return {"status": "activated", "index": index, "query": query, "url": page.url, "title": title}
        raise ValueError(f"No tab matched title or URL containing: {query}")

    async def status(self) -> dict[str, Any]:
        page_ready = False
        page_url: str | None = None
        page_title: str | None = None

        if self._page is not None:
            try:
                page_ready = (
                    self._browser is not None
                    and self._browser.is_connected()
                    and not self._page.is_closed()
                )
                if page_ready:
                    page_url = self._page.url
                    page_title = await self._page.title()
            except Exception:
                await self._reset_connection()
                page_ready = False

        edge_running = self._edge_process is not None and self._edge_process.poll() is None
        return {
            "running": page_ready,
            "edge_running": edge_running,
            "url": page_url,
            "title": page_title,
            "artifacts_dir": str(self.artifacts_dir),
            "browser": "Microsoft Edge",
            "connection_mode": "cdp",
            "cdp_url": self.cdp_url,
            "profile_dir": str(self.profile_dir),
            "persistent_profile": True,
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
        truncated = len(body_text) > max_chars
        if truncated:
            body_text = body_text[:max_chars]
        return {"status": "ok", "text": body_text, "truncated": truncated, **await self._page_summary(page)}

    async def click_text(self, text: str, exact: bool = False) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.get_by_text(text, exact=exact).first.click(timeout=8000)
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
        # 【修改】只有當瀏覽器是由我們啟動時，才執行關閉動作
        if self._edge_process is not None and self._edge_process.poll() is None:
            print("Closing browser session initiated by MCP...")
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass

            self._edge_process.terminate()
            try:
                self._edge_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._edge_process.kill()

        self._edge_process = None
        await self._reset_connection()

        return {"status": "closed"}
