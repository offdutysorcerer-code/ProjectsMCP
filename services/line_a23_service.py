from __future__ import annotations

from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class LineA23Service:
    """Forward MCP tool calls to the local A23 LINE Desktop MCP server."""

    def __init__(self, endpoint: str, timeout_seconds: float = 120) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with streamable_http_client(self.endpoint) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                ) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name,
                        arguments or {},
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                    )
                    if hasattr(result, "model_dump"):
                        return result.model_dump(mode="json", exclude_none=True)
                    return {"result": str(result)}
        except Exception as exc:
            return {
                "isError": True,
                "error": f"A23 MCP forwarding failed: {exc}",
                "endpoint": self.endpoint,
                "tool": name,
            }

    async def status(self) -> dict[str, Any]:
        try:
            async with streamable_http_client(self.endpoint) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=min(self.timeout_seconds, 10)),
                ) as session:
                    info = await session.initialize()
                    tools = await session.list_tools()
                    return {
                        "ok": True,
                        "endpoint": self.endpoint,
                        "server": info.serverInfo.model_dump(mode="json"),
                        "tools": [tool.name for tool in tools.tools],
                    }
        except Exception as exc:
            return {"ok": False, "endpoint": self.endpoint, "error": str(exc)}
