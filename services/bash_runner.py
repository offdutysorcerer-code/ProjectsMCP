from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from services.executable_registry import ExecutableRegistry
from services.process_service import ProcessService


class BashRunner:
    """Optional Bash execution wrapper for Linux/WSL-capable environments."""

    def __init__(self, process_service: ProcessService, executables: ExecutableRegistry) -> None:
        self.process_service = process_service
        self.executables = executables

    def resolve_executable(self) -> str | None:
        return self.executables.get("bash")

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
        shell_name: str = "bash",
    ) -> dict[str, Any]:
        if not command.strip():
            return {"status": "error", "ok": False, "message": "Command is required."}

        workdir, workdir_error = self.resolve_workdir(cwd)
        if workdir_error is not None:
            return workdir_error

        resolved_executable = executable or self.resolve_executable()
        if not resolved_executable:
            return {
                "status": "error",
                "ok": False,
                "message": "Bash executable was not available at A0 startup.",
            }

        process_env = dict(os.environ if env is None else env)
        process_env.setdefault("PYTHONUTF8", "1")
        process_env.setdefault("PYTHONIOENCODING", "utf-8")

        result = self.process_service.run(
            [resolved_executable, "-lc", command],
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
