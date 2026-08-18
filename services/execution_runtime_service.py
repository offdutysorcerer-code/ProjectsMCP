from __future__ import annotations

from pathlib import Path
from typing import Any

from services.bash_runner import BashRunner
from services.command_preflight import CommandPreflightChecker
from services.error_recovery import ErrorClassifier, RecoveryEngine
from services.executable_registry import ExecutableRegistry
from services.known_issues_registry import KnownIssuesRegistry
from services.powershell_runner import PowerShellRunner
from services.process_service import ProcessService


class ExecutionRuntimeService:
    """Central command runtime with preventive rules, preflight, classification, and controlled recovery."""

    def __init__(
        self,
        process_service: ProcessService,
        executables: ExecutableRegistry,
        known_issues: KnownIssuesRegistry,
    ) -> None:
        self.process_service = process_service
        self.executables = executables
        self.known_issues = known_issues
        self.preflight = CommandPreflightChecker(executables)
        self.classifier = ErrorClassifier()
        self.recovery = RecoveryEngine(executables)
        self.powershell_runner = PowerShellRunner(process_service, executables)
        self.bash_runner = BashRunner(process_service, executables)

    @staticmethod
    def _resolve_workdir(cwd: str = "") -> tuple[Path | None, dict[str, Any] | None]:
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

    @staticmethod
    def _public_preflight(preflight: dict[str, Any], process_env: dict[str, str]) -> dict[str, Any]:
        return {
            **preflight,
            "environment": {
                "python_utf8": process_env.get("PYTHONUTF8") == "1",
                "python_io_encoding": process_env.get("PYTHONIOENCODING", ""),
            },
        }

    @staticmethod
    def _classification_payload(classification: Any) -> dict[str, Any]:
        return {
            "code": classification.code,
            "confidence": classification.confidence,
            "retryable": classification.retryable,
            "message": classification.message,
        }

    def _execute_once(
        self,
        *,
        command: str,
        shell: str,
        cwd: str,
        process_env: dict[str, str],
        executable: str | None,
        timeout_seconds: int | None,
    ) -> dict[str, Any]:
        if shell in {"powershell", "pwsh"}:
            return self.powershell_runner.run(
                command,
                cwd=cwd,
                env=process_env,
                timeout_seconds=timeout_seconds,
                executable=executable,
                shell_name=shell,
            )
        if shell == "bash":
            return self.bash_runner.run(
                command,
                cwd=cwd,
                env=process_env,
                timeout_seconds=timeout_seconds,
                executable=executable,
                shell_name=shell,
            )

        workdir, workdir_error = self._resolve_workdir(cwd)
        if workdir_error is not None:
            return workdir_error
        cmd_executable = executable or self.executables.get("cmd")
        if not cmd_executable:
            return {"status": "error", "ok": False, "message": "cmd.exe was not found at A0 startup."}
        result = self.process_service.run(
            [cmd_executable, "/d", "/s", "/c", command],
            cwd=workdir,
            env=process_env,
            timeout_seconds=timeout_seconds,
        )
        return {
            **result,
            "status": "success" if result["ok"] else "timeout" if result["timed_out"] else "error",
            "return_code": result["returncode"],
            "shell": shell,
            "cwd": str(workdir) if workdir else "",
        }

    def run_shell(
        self,
        command: str,
        shell: str,
        *,
        cwd: str = "",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        preventive = self.known_issues.apply_preventive_rules(command, shell)
        preventive_command = str(preventive["command"])
        known_issue_hits = list(preventive["applied"])

        initial_preflight = self.preflight.check(preventive_command, shell, cwd=cwd)
        process_env = initial_preflight.pop("env")
        public_preflight = self._public_preflight(initial_preflight, process_env)
        recovery_steps: list[dict[str, Any]] = []

        if not initial_preflight["ok"]:
            first_error = next((item for item in initial_preflight["issues"] if item["severity"] == "error"), None)
            result = {
                "status": "preflight_failed",
                "ok": False,
                "message": first_error["message"] if first_error else "Command preflight failed.",
                "preflight": public_preflight,
                "known_issues": {"prevented": known_issue_hits},
                "recovery": {"attempted": False, "retry_count": 0, "steps": []},
            }
            result["classification"] = self._classification_payload(self.classifier.classify(result))
            return result

        normalized_shell = str(initial_preflight["shell"])
        normalized_command = str(initial_preflight["command"])
        normalized_cwd = str(initial_preflight["cwd"])
        executable = str(initial_preflight["executable"] or "") or None

        # Fallback recovery remains available for issues not yet promoted to active rules.
        preventive_repair = self.recovery.repair_preflight(initial_preflight)
        if preventive_repair is not None:
            repaired_preflight = self.preflight.check(
                str(preventive_repair["repaired_command"]),
                normalized_shell,
                cwd=normalized_cwd,
                env=process_env,
            )
            repaired_env = repaired_preflight.pop("env")
            if repaired_preflight["ok"]:
                normalized_command = str(repaired_preflight["command"])
                process_env = repaired_env
                public_preflight = self._public_preflight(repaired_preflight, repaired_env)
                recovery_steps.append({**preventive_repair, "phase": "preflight", "validated": True})

        result = self._execute_once(
            command=normalized_command,
            shell=normalized_shell,
            cwd=normalized_cwd,
            process_env=process_env,
            executable=executable,
            timeout_seconds=timeout_seconds,
        )
        result["preflight"] = public_preflight
        result["known_issues"] = {"prevented": known_issue_hits}
        classification = self.classifier.classify(result)

        if not result.get("ok") and classification.code == "command_not_found" and classification.retryable:
            repair = self.recovery.repair_command_not_found(normalized_command)
            if repair is not None:
                retry_preflight = self.preflight.check(
                    repair["repaired_command"],
                    normalized_shell,
                    cwd=normalized_cwd,
                    env=process_env,
                )
                retry_env = retry_preflight.pop("env")
                if retry_preflight["ok"]:
                    recovery_steps.append({**repair, "phase": "post_execution", "validated": True})
                    retry = self._execute_once(
                        command=str(retry_preflight["command"]),
                        shell=str(retry_preflight["shell"]),
                        cwd=str(retry_preflight["cwd"]),
                        process_env=retry_env,
                        executable=str(retry_preflight["executable"] or "") or None,
                        timeout_seconds=timeout_seconds,
                    )
                    retry["preflight"] = self._public_preflight(retry_preflight, retry_env)
                    retry["known_issues"] = {"prevented": known_issue_hits}
                    retry["first_attempt"] = {
                        "status": result.get("status"),
                        "return_code": result.get("return_code", result.get("returncode")),
                        "stderr": result.get("stderr"),
                        "classification": self._classification_payload(classification),
                    }
                    result = retry
                    classification = self.classifier.classify(result)

        result["classification"] = self._classification_payload(classification)
        result["recovery"] = {
            "attempted": bool(recovery_steps),
            "retry_count": sum(1 for step in recovery_steps if step.get("phase") == "post_execution"),
            "steps": recovery_steps,
        }
        return result
