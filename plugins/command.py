from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any

from mcp_platform.context import PlatformContext


class CommandPlugin:
    """Execute shell commands through the shared A0 Execution Runtime."""

    name = "command"
    description = "Execute system commands via cmd, powershell/pwsh, or optional bash."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        process_service = context.process_service

        def _runtime_profile() -> dict[str, Any]:
            project_root = Path(__file__).resolve().parents[1]
            configured_environment = os.environ.get("PROJECTSMCP_ENVIRONMENT", "").strip().upper()
            configured_path = os.environ.get("PROJECTSMCP_CONFIG_PATH", "").strip()
            is_dev = configured_environment == "DEV" or (
                bool(configured_path) and Path(configured_path).name.casefold() == "config.dev.json"
            )
            environment = "DEV" if is_dev else "MAIN"
            return {
                "environment": environment,
                "port": 8091 if is_dev else 8090,
                "script": project_root / "scripts" / (
                    "restart_projectsmcp_dev.ps1" if is_dev else "restart_projectsmcp.ps1"
                ),
                "result_path": project_root / "artifacts" / (
                    Path("dev/restart/latest.json") if is_dev else Path("restart/latest.json")
                ),
            }

        execution_runtime = context.execution_runtime_service

        def _execute_command(
            command: str,
            shell: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            return execution_runtime.run_shell(
                command,
                shell,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )

        @mcp.tool()
        async def run_command(
            command: str,
            shell: str = "cmd",
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a command without blocking the FastMCP event loop."""
            return await asyncio.to_thread(_execute_command, command, shell, cwd, timeout_seconds)

        @mcp.tool()
        async def run_powershell(
            command: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a non-interactive PowerShell command without blocking the FastMCP event loop."""
            return await asyncio.to_thread(_execute_command, command, "powershell", cwd, timeout_seconds)

        @mcp.tool()
        async def run_cmd(
            command: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
            """Execute a CMD command without blocking the FastMCP event loop."""
            return await asyncio.to_thread(_execute_command, command, "cmd", cwd, timeout_seconds)

        @mcp.tool()
        def restart_projectsmcp(
            delay_seconds: int = 3,
            startup_timeout_seconds: int = 30,
        ) -> dict[str, Any]:
            """Schedule a detached ProjectsMCP restart watchdog and return before the current server stops."""
            project_root = Path(__file__).resolve().parents[1]
            profile = _runtime_profile()
            script = Path(profile["script"])
            result_path = Path(profile["result_path"])
            port = int(profile["port"])
            environment = str(profile["environment"])
            if not script.is_file():
                return {"ok": False, "status": "error", "message": f"Restart script not found: {script}"}

            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if not powershell:
                return {"ok": False, "status": "error", "message": "PowerShell executable was not found in PATH."}

            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "environment": environment,
                        "status": "queued",
                        "message": f"{environment} restart watchdog is being launched.",
                        "port": port,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

            def ps_quote(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            watchdog_script = (
                f"& {ps_quote(str(script))} "
                f"-Port {port} "
                f"-DelaySeconds {max(1, int(delay_seconds))} "
                f"-StartupTimeoutSeconds {max(5, int(startup_timeout_seconds))} "
                f"-ResultPath {ps_quote(str(result_path))}"
            )
            watchdog_encoded = base64.b64encode(watchdog_script.encode("utf-16-le")).decode("ascii")
            watchdog_command = (
                f'"{powershell}" -NoLogo -NoProfile -NonInteractive '
                f'-ExecutionPolicy Bypass -EncodedCommand {watchdog_encoded}'
            )
            launcher_script = (
                f"$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                f"-Arguments @{{CommandLine={ps_quote(watchdog_command)}}}; "
                "if([int]$r.ReturnValue -ne 0){ throw ('Win32_Process.Create failed: ' + $r.ReturnValue) }; "
                "$r.ProcessId"
            )
            encoded = base64.b64encode(launcher_script.encode("utf-16-le")).decode("ascii")
            launch = process_service.run(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded,
                ],
                cwd=project_root,
                timeout_seconds=10,
            )
            if not launch.get("ok"):
                result_path.write_text(
                    json.dumps(
                        {
                            "environment": environment,
                            "status": "launch_failed",
                            "message": str(launch.get("stderr") or "Restart watchdog launcher failed."),
                            "port": port,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                return {
                    "ok": False,
                    "status": "launch_failed",
                    "result_path": str(result_path),
                    "process": launch,
                }

            watchdog_pid = str(launch.get("stdout") or "").strip().splitlines()[-1]
            return {
                "ok": True,
                "status": "scheduled",
                "watchdog_pid": watchdog_pid,
                "result_path": str(result_path),
                "message": "ProjectsMCP restart scheduled. Reconnect and call get_restart_status after the endpoint returns.",
            }

        @mcp.tool()
        def get_restart_status() -> dict[str, Any]:
            """Read the latest detached ProjectsMCP restart watchdog result."""
            profile = _runtime_profile()
            environment = str(profile["environment"])
            result_path = Path(profile["result_path"])
            if not result_path.is_file():
                return {"ok": False, "status": "not_found", "message": "No restart status has been recorded yet."}
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"ok": False, "status": "error", "message": f"Unable to read restart status: {exc}"}
            return {"ok": payload.get("status") == "ready", **payload, "result_path": str(result_path)}


def create_plugin() -> CommandPlugin:
    return CommandPlugin()
