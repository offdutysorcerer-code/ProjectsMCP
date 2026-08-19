from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from services.executable_registry import ExecutableRegistry


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    severity: str
    message: str


class CommandPreflightChecker:
    """Validate and normalize shell requests before process launch."""

    _POWERSHELL_ALIASES = {"powershell", "pwsh"}
    _SUPPORTED_SHELLS = _POWERSHELL_ALIASES | {"cmd", "bash"}

    def __init__(self, executables: ExecutableRegistry) -> None:
        self.executables = executables

    def check(
        self,
        command: str,
        shell: str,
        *,
        cwd: str = "",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_shell = shell.strip().lower()
        issues: list[PreflightIssue] = []

        if not command.strip():
            issues.append(PreflightIssue("empty_command", "error", "Command is required."))

        if normalized_shell not in self._SUPPORTED_SHELLS:
            issues.append(
                PreflightIssue(
                    "unsupported_shell",
                    "error",
                    "shell must be 'cmd', 'powershell', 'pwsh', or 'bash'.",
                )
            )

        workdir: Path | None = None
        if cwd:
            try:
                workdir = Path(cwd).expanduser().resolve()
            except OSError as exc:
                issues.append(PreflightIssue("invalid_cwd", "error", f"Unable to resolve working directory: {exc}"))
            else:
                if not workdir.is_dir():
                    issues.append(PreflightIssue("missing_cwd", "error", f"Working directory not found: {cwd}"))

        executable = self._resolve_executable(normalized_shell)
        if normalized_shell in self._SUPPORTED_SHELLS and not executable:
            issues.append(
                PreflightIssue(
                    "missing_executable",
                    "error",
                    f"Executable for shell '{normalized_shell}' was not available at A0 startup.",
                )
            )

        if "\x00" in command:
            issues.append(PreflightIssue("nul_character", "error", "Command contains a NUL character."))

        issues.extend(self._check_known_external_command(command, normalized_shell))
        if normalized_shell in self._POWERSHELL_ALIASES:
            issues.extend(self._check_powershell(command, executable))
            issues.extend(self._check_powershell_modules(command))
        elif normalized_shell == "cmd":
            issues.extend(self._check_cmd(command))

        normalized_env = self._normalize_env(env, normalized_shell)
        return {
            "ok": not any(issue.severity == "error" for issue in issues),
            "shell": normalized_shell,
            "command": command.strip(),
            "cwd": str(workdir) if workdir else "",
            "executable": executable,
            "env": normalized_env,
            "issues": [issue.__dict__ for issue in issues],
        }

    def _resolve_executable(self, shell: str) -> str | None:
        if shell in self._POWERSHELL_ALIASES:
            return self.executables.preferred_powershell(prefer_pwsh=shell == "pwsh" or shell == "powershell")
        if shell == "cmd":
            return self.executables.get("cmd")
        if shell == "bash":
            return self.executables.get("bash")
        return None

    def _check_known_external_command(self, command: str, shell: str) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        first_segment = re.split(r"[;&|]", command, maxsplit=1)[0].strip()
        if not first_segment:
            return issues
        match = re.match(r"(?:&\s*)?[\"']?([A-Za-z0-9_.-]+)", first_segment)
        if not match:
            return issues
        name = match.group(1).casefold()
        aliases = {
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
        registry_name = aliases.get(name)
        if registry_name and not self.executables.get(registry_name):
            issues.append(
                PreflightIssue(
                    "missing_command",
                    "error",
                    f"Command '{name}' was not available in the A0 startup executable registry.",
                )
            )
        return issues

    @staticmethod
    def _check_powershell_modules(command: str) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        for match in re.finditer(r"\bImport-Module\s+(?:-Name\s+)?[\"']?([^\s;\"']+)", command, re.IGNORECASE):
            module = match.group(1)
            if any(sep in module for sep in ("\\", "/")) or module.casefold().endswith((".psd1", ".psm1", ".dll")):
                candidate = Path(module).expanduser()
                if not candidate.is_file():
                    issues.append(
                        PreflightIssue(
                            "missing_module_path",
                            "error",
                            f"PowerShell module path does not exist: {module}",
                        )
                    )
                continue
            module_found = False
            for root in os.environ.get("PSModulePath", "").split(os.pathsep):
                if not root.strip():
                    continue
                base = Path(root) / module
                if base.exists():
                    module_found = True
                    break
            if not module_found:
                issues.append(
                    PreflightIssue(
                        "module_not_found",
                        "warning",
                        f"PowerShell module '{module}' was not found in the current PSModulePath snapshot.",
                    )
                )
        return issues

    def _check_powershell(self, command: str, executable: str | None) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        executable_name = Path(executable).name.casefold() if executable else ""
        is_windows_powershell = executable_name == "powershell.exe"

        if is_windows_powershell and re.search(r"\bForEach-Object\s+-Parallel\b", command, re.IGNORECASE):
            issues.append(
                PreflightIssue(
                    "powershell_version_incompatible",
                    "error",
                    "ForEach-Object -Parallel requires PowerShell 7+; startup registry selected Windows PowerShell 5.1.",
                )
            )

        if re.search(r"(^|[;&|]\s*)cd\s+/d\b", command, re.IGNORECASE):
            issues.append(
                PreflightIssue(
                    "cmd_syntax_in_powershell",
                    "warning",
                    "Command contains CMD-style 'cd /d'; use Set-Location or provide cwd instead.",
                )
            )

        issues.extend(self._check_powershell_patch_risk(command))

        if command.count('"') % 2:
            issues.append(
                PreflightIssue(
                    "unbalanced_double_quote",
                    "warning",
                    "Command contains an odd number of double quotes; verify quoting before execution.",
                )
            )
        return issues

    @staticmethod
    def _check_powershell_patch_risk(command: str) -> list[PreflightIssue]:
        """Flag inline PowerShell that is acting as a large source-code patcher.

        Individual file/process primitives remain allowed. Blocking requires a combination
        of a long inline command, source-like file targets, and multiple text-rewrite
        primitives. This keeps normal administration commands usable while steering code
        edits to structured MCP file operations.
        """
        issues: list[PreflightIssue] = []
        if len(command) < 800:
            return issues

        source_target = bool(
            re.search(r"\.(?:ps1|psm1|py|cs|js|ts|tsx|jsx|json|ya?ml|toml|md)(?:[\"'\s;]|$)", command, re.IGNORECASE)
        )
        rewrite_markers = (
            r"\bReadAllText\b",
            r"\bWriteAllText\b",
            r"\.Replace\s*\(",
            r"\.IndexOf\s*\(",
            r"\.Substring\s*\(",
            r"\bSet-Content\b",
            r"\bAdd-Content\b",
        )
        rewrite_hits = sum(1 for pattern in rewrite_markers if re.search(pattern, command, re.IGNORECASE))
        process_markers = (
            r"\bStart-Process\b",
            r"-WindowStyle\s+Hidden\b",
            r"\btaskkill(?:\.exe)?\b",
            r"\bStop-Process\b",
            r"\bWin32_Process\b",
        )
        process_hits = sum(1 for pattern in process_markers if re.search(pattern, command, re.IGNORECASE))

        if len(command) >= 1200 and source_target and rewrite_hits >= 2:
            detail = ""
            if process_hits:
                detail = " The same command also contains hidden/process-control behavior."
            issues.append(
                PreflightIssue(
                    "prefer_structured_file_edit",
                    "error",
                    "Large inline PowerShell appears to be patching source/configuration files. "
                    "Use MCP FileService operations such as replace_text/write_file or a dedicated patch service instead of pwsh -Command."
                    + detail,
                )
            )
        elif rewrite_hits >= 2 or (source_target and process_hits >= 2):
            issues.append(
                PreflightIssue(
                    "powershell_inline_patch_risk",
                    "warning",
                    "Long inline PowerShell combines file-rewrite or process-control primitives. Prefer structured FileService operations when modifying code.",
                )
            )
        return issues

    @staticmethod
    def _check_cmd(command: str) -> list[PreflightIssue]:
        issues: list[PreflightIssue] = []
        if re.search(r"\$env:[A-Za-z_]", command):
            issues.append(
                PreflightIssue(
                    "powershell_syntax_in_cmd",
                    "warning",
                    "Command contains PowerShell-style $env: syntax while shell=cmd.",
                )
            )
        return issues

    @staticmethod
    def _normalize_env(env: Mapping[str, str] | None, shell: str) -> dict[str, str]:
        normalized = dict(os.environ if env is None else env)
        if shell in CommandPreflightChecker._POWERSHELL_ALIASES or shell == "bash":
            normalized.setdefault("PYTHONUTF8", "1")
            normalized.setdefault("PYTHONIOENCODING", "utf-8")
        return normalized
