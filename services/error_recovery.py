from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.executable_registry import ExecutableRegistry


@dataclass(frozen=True)
class ErrorClassification:
    code: str
    confidence: str
    retryable: bool
    message: str


class ErrorClassifier:
    """Classify execution failures into stable categories for controlled recovery."""

    def classify(self, result: dict[str, Any]) -> ErrorClassification:
        if result.get("timed_out"):
            return ErrorClassification(
                "timeout",
                "high",
                False,
                "Command exceeded its timeout and the process tree was terminated.",
            )

        status = str(result.get("status") or "")
        if status == "preflight_failed":
            issues = (result.get("preflight") or {}).get("issues") or []
            code = str((issues[0] if issues else {}).get("code") or "preflight_failed")
            return ErrorClassification(code, "high", False, str(result.get("message") or "Preflight failed."))

        stderr = str(result.get("stderr") or "")
        stdout = str(result.get("stdout") or "")
        combined = f"{stderr}\n{stdout}".casefold()

        command_not_found_markers = (
            "is not recognized as an internal or external command",
            "the term '",
            "is not recognized as a name of a cmdlet",
            "commandnotfoundexception",
        )
        if any(marker in combined for marker in command_not_found_markers):
            return ErrorClassification(
                "command_not_found",
                "high",
                True,
                "The shell could not resolve the invoked command.",
            )

        if "execution of scripts is disabled" in combined or "authorizationmanager check failed" in combined:
            return ErrorClassification(
                "execution_policy",
                "high",
                False,
                "PowerShell script execution was blocked by execution policy.",
            )

        if "cannot find path" in combined or "pathnotfound" in combined:
            return ErrorClassification("path_not_found", "high", False, "A referenced path was not found.")

        if "could not be loaded because no valid module file was found" in combined:
            return ErrorClassification("module_not_found", "high", False, "A requested PowerShell module was not found.")

        if result.get("ok"):
            if stderr.strip():
                return ErrorClassification(
                    "success_with_stderr",
                    "medium",
                    False,
                    "Command returned success but also wrote to stderr.",
                )
            return ErrorClassification("success", "high", False, "Command completed successfully.")

        return ErrorClassification("process_error", "low", False, "Command failed without a recognized recoverable signature.")


class RecoveryEngine:
    """Apply narrowly-scoped, auditable repairs with at most one retry."""

    _KNOWN_COMMANDS = {
        "python": "python",
        "python.exe": "python",
        "uv": "uv",
        "uv.exe": "uv",
        "git": "git",
        "git.exe": "git",
        "node": "node",
        "node.exe": "node",
        "codex": "codex",
        "codex.exe": "codex",
        "pwsh": "pwsh",
        "pwsh.exe": "pwsh",
        "powershell": "powershell",
        "powershell.exe": "powershell",
    }

    def __init__(self, executables: ExecutableRegistry) -> None:
        self.executables = executables

    def repair_preflight(self, preflight: dict[str, Any]) -> dict[str, Any] | None:
        shell = str(preflight.get("shell") or "")
        command = str(preflight.get("command") or "")
        issue_codes = {str(item.get("code") or "") for item in preflight.get("issues") or []}
        if shell in {"powershell", "pwsh"} and "cmd_syntax_in_powershell" in issue_codes:
            match = re.match(r"^\s*cd\s+/d\s+([^;&|]+)([;&|].*)?$", command, re.IGNORECASE)
            if not match:
                return None
            raw_path = match.group(1).strip().strip('"')
            if not raw_path or any(ch in raw_path for ch in "`$\r\n"):
                return None
            remainder = match.group(2) or ""
            quoted = "'" + raw_path.replace("'", "''") + "'"
            repaired = f"Set-Location -LiteralPath {quoted}{remainder}"
            return {
                "code": "cmd_cd_to_set_location",
                "original_command": command,
                "repaired_command": repaired,
                "reason": "Converted unambiguous CMD-style cd /d to PowerShell Set-Location.",
            }
        return None

    def repair_command_not_found(self, command: str) -> dict[str, str] | None:
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)(\s+.*)?$", command, re.DOTALL)
        if not match:
            return None
        token = match.group(1).casefold()
        registry_name = self._KNOWN_COMMANDS.get(token)
        if not registry_name:
            return None
        resolved = self.executables.get(registry_name)
        if not resolved:
            return None
        remainder = match.group(2) or ""
        repaired = f'"{resolved}"{remainder}'
        if repaired == command.strip():
            return None
        return {
            "code": "use_registry_full_path",
            "original_command": command,
            "repaired_command": repaired,
            "reason": f"Replaced '{token}' with the frozen startup executable path.",
        }
