from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class McpDiagnosticsPlugin:
    name = "mcp_diagnostics"
    description = "Report local, public, tunnel, connector, and server process identity."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.mcp_diagnostics_service

        @mcp.tool()
        def mcp_diagnostics() -> dict[str, Any]:
            """Diagnose endpoint drift and identify the running ProjectsMCP process."""
            return service.status()


def create_plugin() -> McpDiagnosticsPlugin:
    return McpDiagnosticsPlugin()
