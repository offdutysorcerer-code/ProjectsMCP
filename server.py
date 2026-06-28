from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_platform.context import PlatformContext
from mcp_platform.plugin_registry import PluginRegistry
from services.browser_service import BrowserService
from services.config_service import ConfigService
from services.file_service import FileService
from services.git_service import GitService
from services.process_service import ProcessService

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
ARTIFACTS_DIR = APP_DIR / "artifacts"

mcp = FastMCP("ProjectsMCP Platform")
config_service = ConfigService(CONFIG_PATH)
file_service = FileService(config_service)
browser_service = BrowserService(ARTIFACTS_DIR / "browser")
settings = config_service.get_settings()
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
context = PlatformContext(
    config_service=config_service,
    file_service=file_service,
    browser_service=browser_service,
    git_service=git_service,
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
