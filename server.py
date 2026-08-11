from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_platform.audit_logging import install_tool_audit
from mcp_platform.context import PlatformContext
from mcp_platform.plugin_registry import PluginRegistry
from services.a3_2_service import A3_2Service
from services.browser_service import BrowserService
from services.config_service import ConfigService
from services.desktop_service import DesktopService
from services.file_service import FileService
from services.git_service import GitService
from services.line_a23_service import LineA23Service
from services.local_agent_service import LocalAgentService
from services.process_service import ProcessService

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
ARTIFACTS_DIR = APP_DIR / "artifacts"

mcp = FastMCP("ProjectsMCP Platform")
install_tool_audit(mcp)
config_service = ConfigService(CONFIG_PATH)
file_service = FileService(config_service)
browser_service = BrowserService(ARTIFACTS_DIR / "browser")
desktop_service = DesktopService(APP_DIR / "scripts" / "mouse_overlay.ps1")
settings = config_service.get_settings()
a3_2_service = A3_2Service(
    base_url=str(settings.get("a3_2_endpoint", "http://127.0.0.1:5139")),
    timeout_seconds=float(settings.get("a3_2_timeout_seconds", 120)),
    artifacts_dir=ARTIFACTS_DIR / "a3_2",
)
line_a23_service = LineA23Service(
    endpoint=str(settings.get("line_a23_endpoint", "http://127.0.0.1:3000/mcp")),
    timeout_seconds=float(settings.get("line_a23_timeout_seconds", 120)),
)
process_service = ProcessService(
    default_timeout_seconds=int(settings.get("command_timeout_seconds", 60)),
    max_output_bytes=int(settings.get("max_command_output_bytes", 2097152)),
    kill_grace_seconds=int(settings.get("process_kill_grace_seconds", 3)),
)
git_service = GitService(
    file_service,
    process_service,
    default_timeout_seconds=int(settings.get("git_timeout_seconds", 60)),
)
local_agent_service = LocalAgentService(
    file_service=file_service,
    process_service=process_service,
    worker_dir=Path(str(settings.get("local_agent_worker_dir", r"D:\AIProjects\A28-Agent2AgentWithLMStudio"))),
    timeout_seconds=int(settings.get("local_agent_timeout_seconds", 180)),
    max_concurrent_jobs=int(settings.get("local_agent_max_concurrent_jobs", 4)),
)
context = PlatformContext(
    a3_2_service=a3_2_service,
    config_service=config_service,
    file_service=file_service,
    browser_service=browser_service,
    desktop_service=desktop_service,
    git_service=git_service,
    line_a23_service=line_a23_service,
    local_agent_service=local_agent_service,
    process_service=process_service,
)
registry = PluginRegistry(context)
registry.load_enabled_plugins(config_service.get_enabled_plugins())


@mcp.tool()
def list_plugins() -> dict[str, Any]:
    """List enabled MCP Platform plugins."""
    return registry.list_plugins()


registry.register_tools(mcp)


if __name__ == "__main__":
    mcp.run()
