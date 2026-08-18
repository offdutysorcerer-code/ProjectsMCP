from __future__ import annotations

from dataclasses import dataclass

from services.a3_2_service import A3_2Service
from services.browser_service import BrowserService
from services.codex_agent_service import CodexAgentService
from services.config_service import ConfigService
from services.desktop_service import DesktopService
from services.execution_runtime_service import ExecutionRuntimeService
from services.file_service import FileService
from services.git_service import GitService
from services.line_a23_service import LineA23Service
from services.local_agent_service import LocalAgentService
from services.mcp_diagnostics_service import McpDiagnosticsService
from services.process_service import ProcessService
from services.runtime_telemetry_service import RuntimeTelemetryService


@dataclass(frozen=True)
class PlatformContext:
    """Shared services passed to every MCP Platform plugin."""

    a3_2_service: A3_2Service
    config_service: ConfigService
    file_service: FileService
    browser_service: BrowserService
    codex_agent_service: CodexAgentService
    desktop_service: DesktopService
    execution_runtime_service: ExecutionRuntimeService
    git_service: GitService
    line_a23_service: LineA23Service
    local_agent_service: LocalAgentService
    mcp_diagnostics_service: McpDiagnosticsService
    process_service: ProcessService
    runtime_telemetry_service: RuntimeTelemetryService
