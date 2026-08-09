from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class LineA23Plugin:
    name = "line_a23"
    description = "Forward LINE Desktop operations to the local A23 MCP service."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.line_a23_service

        @mcp.tool()
        async def line_a23_status() -> dict[str, Any]:
            """Check whether the A23 LINE Desktop MCP service is reachable and list its tools."""
            return await service.status()

        @mcp.tool()
        async def get_line_chatroom_history_default(
            chatName: str,
            date: str | None = None,
            messageLimit: int = 100,
        ) -> dict[str, Any]:
            """Forward a normal LINE chat-history request to A23."""
            args = {"chatName": chatName, "messageLimit": messageLimit}
            if date:
                args["date"] = date
            return await service.call_tool("get_line_chatroom_history_default", args)

        @mcp.tool()
        async def get_line_chatroom_history_long(
            chatName: str,
            date: str | None = None,
            messageLimit: int = 100,
        ) -> dict[str, Any]:
            """Forward a long LINE chat-history request to A23."""
            args = {"chatName": chatName, "messageLimit": messageLimit}
            if date:
                args["date"] = date
            return await service.call_tool("get_line_chatroom_history_long", args)

        @mcp.tool()
        async def get_line_chatroom_history_short(
            chatName: str,
            date: str | None = None,
            messageLimit: int = 100,
        ) -> dict[str, Any]:
            """Forward a short LINE chat-history request to A23."""
            args = {"chatName": chatName, "messageLimit": messageLimit}
            if date:
                args["date"] = date
            return await service.call_tool("get_line_chatroom_history_short", args)

        @mcp.tool()
        async def send_message_manual(chatName: str, message: str) -> dict[str, Any]:
            """Forward a LINE draft request to A23 without automatic sending."""
            return await service.call_tool(
                "send_message_manual", {"chatName": chatName, "message": message}
            )

        @mcp.tool()
        async def send_message_auto(chatName: str, message: str) -> dict[str, Any]:
            """Forward an explicitly authorized immediate LINE send request to A23."""
            return await service.call_tool(
                "send_message_auto", {"chatName": chatName, "message": message}
            )


def create_plugin() -> LineA23Plugin:
    return LineA23Plugin()
