from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from mcp_platform.context import PlatformContext


class CommandPlugin:
    """Execute CMD and PowerShell commands with hard timeout boundaries."""

    name = "command"
    description = "Execute system commands via cmd or powershell."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        process_service = context.process_service

        @mcp.tool()
        def run_command(
            command: str,
            shell: str = "cmd",
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a command with bounded output and terminate its process tree on timeout."""
            if not command.strip():
                return {"status": "error", "ok": False, "message": "Command is required."}

            workdir: Path | None = None
            if cwd:
                workdir = Path(cwd).expanduser().resolve()
                if not workdir.is_dir():
                    return {
                        "status": "error",
                        "ok": False,
                        "message": f"Working directory not found: {cwd}",
                    }

            normalized_shell = shell.strip().lower()
            if normalized_shell in {"powershell", "pwsh"}:
                executable = shutil.which("pwsh") or shutil.which("powershell")
                if not executable:
                    return {
                        "status": "error",
                        "ok": False,
                        "message": "PowerShell executable was not found in PATH.",
                    }
                cmd = [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ]
            elif normalized_shell == "cmd":
                executable = os.environ.get("COMSPEC") or shutil.which("cmd")
                if not executable:
                    return {
                        "status": "error",
                        "ok": False,
                        "message": "cmd.exe was not found.",
                    }
                cmd = [executable, "/d", "/s", "/c", command]
            else:
                return {
                    "status": "error",
                    "ok": False,
                    "message": "shell must be 'cmd', 'powershell', or 'pwsh'.",
                }

            result = process_service.run(
                cmd,
                cwd=workdir,
                timeout_seconds=timeout_seconds,
            )
            return {
                **result,
                "status": "success" if result["ok"] else "timeout" if result["timed_out"] else "error",
                "return_code": result["returncode"],
                "shell": normalized_shell,
                "cwd": str(workdir) if workdir else "",
            }

        @mcp.tool()
        def run_powershell(
            command: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a non-interactive PowerShell command."""
            return run_command(
                command,
                shell="powershell",
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )

        @mcp.tool()
        def run_cmd(
            command: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a CMD command."""
            return run_command(
                command,
                shell="cmd",
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )


def create_plugin() -> CommandPlugin:
    return CommandPlugin()
