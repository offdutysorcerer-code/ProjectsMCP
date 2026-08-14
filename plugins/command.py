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
    """Execute CMD and PowerShell commands with hard timeout boundaries."""

    name = "command"
    description = "Execute system commands via cmd or powershell."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        process_service = context.process_service

        def _execute_command(
            command: str,
            shell: str,
            cwd: str = "",
            timeout_seconds: int | None = None,
        ) -> dict[str, Any]:
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
            script = project_root / "scripts" / "restart_projectsmcp.ps1"
            result_path = project_root / "artifacts" / "restart" / "latest.json"
            if not script.is_file():
                return {"ok": False, "status": "error", "message": f"Restart script not found: {script}"}

            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if not powershell:
                return {"ok": False, "status": "error", "message": "PowerShell executable was not found in PATH."}

            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(
                    {
                        "status": "queued",
                        "message": "Restart watchdog is being launched.",
                        "port": 8090,
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
                f"-Port 8090 "
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
                            "status": "launch_failed",
                            "message": str(launch.get("stderr") or "Restart watchdog launcher failed."),
                            "port": 8090,
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
            project_root = Path(__file__).resolve().parents[1]
            result_path = project_root / "artifacts" / "restart" / "latest.json"
            if not result_path.is_file():
                return {"ok": False, "status": "not_found", "message": "No restart status has been recorded yet."}
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"ok": False, "status": "error", "message": f"Unable to read restart status: {exc}"}
            return {"ok": payload.get("status") == "ready", **payload, "result_path": str(result_path)}


def create_plugin() -> CommandPlugin:
    return CommandPlugin()
