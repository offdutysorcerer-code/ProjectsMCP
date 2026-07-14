from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class BrowserPlugin:
    """Browser automation plugin backed by Playwright Async API."""

    name = "browser"
    description = "Open web pages, navigate, click, fill forms, extract text, and save screenshots."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        browser_service = context.browser_service

        @mcp.tool()
        async def browser_status() -> dict[str, Any]:
            """Return the current browser session status."""
            return await browser_service.status()

        @mcp.tool()
        async def browser_open(url: str = "", headless: bool = False) -> dict[str, Any]:
            """Open a Chromium browser session, optionally navigating to a URL."""
            return await browser_service.open(url, headless)

        @mcp.tool()
        async def browser_tabs() -> dict[str, Any]:
            """List all open browser tabs with index, title, URL, and active state."""
            return await browser_service.tabs()

        @mcp.tool()
        async def browser_switch_tab(index: int) -> dict[str, Any]:
            """Switch to an open browser tab by zero-based index."""
            return await browser_service.switch_tab(index)

        @mcp.tool()
        async def browser_new_tab(url: str = "") -> dict[str, Any]:
            """Open a new browser tab, optionally navigating to a URL."""
            return await browser_service.new_tab(url)

        @mcp.tool()
        async def browser_close_tab(index: int | None = None) -> dict[str, Any]:
            """Close a browser tab by index, or close the active tab when omitted."""
            return await browser_service.close_tab(index)

        @mcp.tool()
        async def browser_activate_tab(query: str) -> dict[str, Any]:
            """Activate the first tab whose title or URL contains the query."""
            return await browser_service.activate_tab(query)

        @mcp.tool()
        async def browser_goto(url: str) -> dict[str, Any]:
            """Navigate the active browser page to a URL."""
            return await browser_service.goto(url)

        @mcp.tool()
        async def browser_back() -> dict[str, Any]:
            """Navigate the active browser page back one step."""
            return await browser_service.back()

        @mcp.tool()
        async def browser_text(max_chars: int = 12000) -> dict[str, Any]:
            """Extract visible body text from the active browser page."""
            return await browser_service.text(max_chars)

        @mcp.tool()
        async def browser_click_text(text: str, exact: bool = False) -> dict[str, Any]:
            """Click the first visible element matching text on the active page."""
            return await browser_service.click_text(text, exact)

        @mcp.tool()
        async def browser_fill(selector: str, value: str) -> dict[str, Any]:
            """Fill the first element matching a CSS selector."""
            return await browser_service.fill(selector, value)

        @mcp.tool()
        async def browser_press(key: str) -> dict[str, Any]:
            """Send a keyboard key press to the active page, such as Enter or Tab."""
            return await browser_service.press(key)

        @mcp.tool()
        async def browser_screenshot(full_page: bool = True) -> dict[str, Any]:
            """Save a PNG screenshot of the active page and return its local path."""
            return await browser_service.screenshot(full_page)

        @mcp.tool()
        async def browser_close() -> dict[str, Any]:
            """Close the browser session."""
            return await browser_service.close()


def create_plugin() -> BrowserPlugin:
    return BrowserPlugin()
