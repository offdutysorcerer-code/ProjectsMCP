from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Protocol

from mcp_platform.context import PlatformContext


class MCPPlugin(Protocol):
    """Contract implemented by every MCP Platform plugin."""

    name: str
    description: str

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        """Register this plugin's tools on a FastMCP instance."""


@dataclass(frozen=True)
class LoadedPlugin:
    name: str
    description: str
    module: str


class PluginRegistry:
    """Loads enabled plugins and asks them to register MCP tools."""

    def __init__(self, context: PlatformContext) -> None:
        self.context = context
        self._plugins: list[MCPPlugin] = []
        self._loaded: list[LoadedPlugin] = []

    def load_enabled_plugins(self, plugin_names: list[str]) -> None:
        for plugin_name in plugin_names:
            module_name = f"plugins.{plugin_name}"
            module = importlib.import_module(module_name)
            plugin_factory = getattr(module, "create_plugin")
            plugin = plugin_factory()
            self._plugins.append(plugin)
            self._loaded.append(
                LoadedPlugin(
                    name=plugin.name,
                    description=plugin.description,
                    module=module_name,
                )
            )

    def register_tools(self, mcp: Any) -> None:
        for plugin in self._plugins:
            plugin.register_tools(mcp, self.context)

    def list_plugins(self) -> dict[str, Any]:
        return {
            "plugins": [
                {
                    "name": plugin.name,
                    "description": plugin.description,
                    "module": plugin.module,
                }
                for plugin in self._loaded
            ]
        }
