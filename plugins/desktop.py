from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class DesktopPlugin:
    name = "desktop"
    description = "Control the Windows mouse with a visible highlight overlay."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.desktop_service

        @mcp.tool()
        def mouse_highlight_start(color: str = "#00E5FF", size: int = 64) -> dict[str, Any]:
            """Start a click-through glowing ring that follows the mouse cursor."""
            return service.start_overlay(color=color, size=size)

        @mcp.tool()
        def mouse_highlight_stop() -> dict[str, Any]:
            """Stop the mouse highlight overlay started by this MCP server."""
            return service.stop_overlay()

        @mcp.tool()
        def mouse_highlight_status() -> dict[str, Any]:
            """Return whether the mouse highlight overlay is running."""
            return service.overlay_status()

        @mcp.tool()
        def mouse_get_position() -> dict[str, Any]:
            """Return the current Windows mouse cursor coordinates."""
            return service.get_mouse_position()

        @mcp.tool()
        def mouse_move(x: int, y: int) -> dict[str, Any]:
            """Move the Windows mouse cursor to absolute screen coordinates."""
            return service.move_mouse(x, y)

        @mcp.tool()
        def mouse_click(button: str = "left", clicks: int = 1) -> dict[str, Any]:
            """Click the current cursor position using left, right, or middle button."""
            return service.click_mouse(button=button, clicks=clicks)


def create_plugin() -> DesktopPlugin:
    return DesktopPlugin()
