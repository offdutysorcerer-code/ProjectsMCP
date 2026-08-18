from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from services.executable_registry import ExecutableRegistry
from services.process_service import ProcessService


class PowerShellRunner:
    """Standardized PowerShell execution wrapper for A0."""

    UTF8_BOOTSTRAP = (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    )

    def __init__(self, process_service: ProcessService, executables: ExecutableRegistry) -> None:
        self.process_service = process_service
        self.executables = executables

    def resolve_executable(self, prefer_pwsh: bool = True) -> str | None:
        return self.executables.preferred_powershell(prefer_pwsh=prefer_pwsh)

    @staticmethod
    def resolve_workdir(cwd: str = "") -> tuple[Path | None, dict[str, Any] | None]:
        if not cwd:
            return None, None
        workdir = Path(cwd).expanduser().resolve()
        if not workdir.is_dir():
            return None, {
                "status": "error",
                "ok": False,
                "message": f"Working directory not found: {cwd}",
            }
        return workdir, None

    def run(
        self,
        command: str,
        *,
        cwd: str = "",
        env: Mapping[str, str] | None = None,
        timeout_seconds: int | None = None,
        executable: str | None = None,
        shell_name: str = "powershell",
    ) -> dict[str, Any]:
        if not command.strip():
            return {"status": "error", "ok": False, "message": "Command is required."}

        workdir, workdir_error = self.resolve_workdir(cwd)
        if workdir_error is not None:
            return workdir_error

        resolved_executable = executable or self.resolve_executable(prefer_pwsh=shell_name != "powershell.exe")
        if not resolved_executable:
            return {
                "status": "error",
                "ok": False,
                "message": "PowerShell executable was not found in PATH.",
            }

        process_command = [
            resolved_executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            self.UTF8_BOOTSTRAP + command,
        ]
        process_env = dict(os.environ if env is None else env)
        process_env.setdefault("PYTHONUTF8", "1")
        process_env.setdefault("PYTHONIOENCODING", "utf-8")

        result = self.process_service.run(
            process_command,
            cwd=workdir,
            env=process_env,
            timeout_seconds=timeout_seconds,
        )
        return {
            **result,
            "status": "success" if result["ok"] else "timeout" if result["timed_out"] else "error",
            "return_code": result["returncode"],
            "shell": shell_name,
            "executable": resolved_executable,
            "cwd": str(workdir) if workdir else "",
        }
