from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class RuntimeTelemetryPlugin:
    name = "runtime_telemetry"
    description = "Expose A0 runtime orchestration snapshot and recent telemetry events."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.runtime_telemetry_service

        @mcp.tool()
        def runtime_snapshot() -> dict[str, Any]:
            """Return the current A0 orchestration runtime snapshot."""
            return service.snapshot()

        @mcp.tool()
        def runtime_recent_events(limit: int = 100) -> dict[str, Any]:
            """Return recent normalized A0 runtime events."""
            return service.recent_events(limit)


def create_plugin() -> RuntimeTelemetryPlugin:
    return RuntimeTelemetryPlugin()
