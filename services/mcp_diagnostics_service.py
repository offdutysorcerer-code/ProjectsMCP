from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from services.config_service import ConfigService


class McpDiagnosticsService:
    """Expose stable endpoint and process identity information for connector diagnosis."""

    def __init__(self, config_service: ConfigService) -> None:
        self.config_service = config_service
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.process_id = os.getpid()

    def status(self) -> dict[str, Any]:
        endpoint = self.config_service.get_settings().get("endpoint", {})
        if not isinstance(endpoint, dict):
            endpoint = {}

        public_url = str(endpoint.get("public_sse_url", ""))
        connector_url = str(endpoint.get("active_connector_endpoint", ""))
        environment = os.environ.get("PROJECTSMCP_ENVIRONMENT", "").strip().upper() or "MAIN"
        artifacts_dir = os.environ.get("PROJECTSMCP_ARTIFACTS_DIR", "").strip()
        return {
            "server_name": "ProjectsMCP Platform",
            "environment": environment,
            "config_path": str(self.config_service.config_path),
            "artifacts_dir": artifacts_dir,
            "local_sse_url": str(endpoint.get("local_sse_url", "")),
            "public_sse_url": public_url,
            "active_tunnel_provider": str(endpoint.get("active_tunnel_provider", "unknown")),
            "active_connector_endpoint": connector_url,
            "connector_endpoint_matches_public": bool(public_url) and connector_url == public_url,
            "server_start_time": self.started_at,
            "process_id": self.process_id,
            "plugin_config_generation_source": str(
                endpoint.get("generation_source", "config.json:settings.endpoint")
            ),
            "connector_registration_mode": "install-time snapshot outside the MCP server",
        }
