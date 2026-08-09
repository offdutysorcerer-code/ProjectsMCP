from __future__ import annotations

from dataclasses import dataclass

from services.browser_service import BrowserService
from services.config_service import ConfigService
from services.desktop_service import DesktopService
from services.file_service import FileService
from services.git_service import GitService
from services.line_a23_service import LineA23Service
from services.process_service import ProcessService


@dataclass(frozen=True)
class PlatformContext:
    """Shared services passed to every MCP Platform plugin."""

    config_service: ConfigService
    file_service: FileService
    browser_service: BrowserService
    desktop_service: DesktopService
    git_service: GitService
    line_a23_service: LineA23Service
    process_service: ProcessService
