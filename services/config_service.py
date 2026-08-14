from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"config.json not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)

        projects = config.get("projects", {})
        if not isinstance(projects, dict) or not projects:
            raise ValueError("config.json must contain a non-empty 'projects' object")

        return config

    def get_projects(self) -> dict[str, str]:
        return self.load_config()["projects"]

    def get_settings(self) -> dict[str, Any]:
        return self.load_config().get("settings", {})

    def get_enabled_plugins(self) -> list[str]:
        default_plugins = ["project", "browser"]
        plugins = self.load_config().get("plugins", {})
        enabled = plugins.get("enabled", default_plugins) if isinstance(plugins, dict) else default_plugins
        if not isinstance(enabled, list) or not enabled:
            return default_plugins
        return [str(plugin_name) for plugin_name in enabled]

    def get_max_read_bytes(self) -> int:
        return int(self.get_settings().get("max_read_bytes", 1048576))

    def get_max_pdf_read_bytes(self) -> int:
        return int(self.get_settings().get("max_pdf_read_bytes", 26214400))

    def get_allowed_write_extensions(self) -> set[str]:
        values = self.get_settings().get("allowed_write_extensions", [])
        return {str(value).lower() for value in values}

    def get_default_exclude_patterns(self) -> list[str]:
        values = self.get_settings().get("default_exclude_patterns")
        if isinstance(values, list):
            return [str(value) for value in values]
        return [".git", "node_modules", "bin", "obj", ".venv", "__pycache__", "dist", "build", "artifacts"]
