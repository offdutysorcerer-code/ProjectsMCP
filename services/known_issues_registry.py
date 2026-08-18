from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from services.executable_registry import ExecutableRegistry


@dataclass(frozen=True)
class KnownIssueRule:
    rule_id: str
    issue_code: str
    status: str
    description: str
    action: str
    recovery_validated: bool
    validator_passed: bool
    source: str
    mode: str = "preventive"

    @property
    def active(self) -> bool:
        return self.status == "active" and self.recovery_validated and self.validator_passed


class KnownIssuesRegistry:
    """Versioned known-issue policies promoted only after validated evidence."""

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
    }

    def __init__(self, path: Path, executables: ExecutableRegistry) -> None:
        self.path = path.resolve()
        self.executables = executables
        self._rules = self._load()

    def _load(self) -> dict[str, KnownIssueRule]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        items = payload.get("rules") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return {}
        rules: dict[str, KnownIssueRule] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                rule = KnownIssueRule(**item)
            except TypeError:
                continue
            rules[rule.rule_id] = rule
        return rules

    def _save(self) -> None:
        payload = {"schema_version": 1, "rules": [asdict(rule) for rule in self._rules.values()]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def register_candidate(
        self,
        *,
        rule_id: str,
        issue_code: str,
        description: str,
        action: str,
        source: str,
        mode: str = "preventive",
    ) -> KnownIssueRule:
        key = rule_id.strip()
        if not key:
            raise ValueError("rule_id is required")
        existing = self._rules.get(key)
        if existing is not None:
            return existing
        rule = KnownIssueRule(
            rule_id=key,
            issue_code=issue_code.strip(),
            status="candidate",
            description=description.strip(),
            action=action.strip(),
            recovery_validated=False,
            validator_passed=False,
            source=source.strip(),
            mode=mode.strip() or "preventive",
        )
        self._rules[key] = rule
        self._save()
        return rule

    def promote(
        self,
        rule_id: str,
        *,
        recovery_validated: bool,
        validator_passed: bool,
        source: str,
    ) -> KnownIssueRule:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise KeyError(f"Known issue rule not found: {rule_id}")
        if not recovery_validated or not validator_passed:
            raise ValueError("Rule promotion requires both successful recovery validation and validator pass.")
        promoted = replace(
            rule,
            status="active",
            recovery_validated=True,
            validator_passed=True,
            source=source.strip() or rule.source,
        )
        self._rules[rule_id] = promoted
        self._save()
        return promoted

    def snapshot(self) -> dict[str, Any]:
        items = [asdict(rule) | {"active": rule.active} for rule in self._rules.values()]
        by_mode: dict[str, int] = {}
        for item in items:
            mode = str(item.get("mode") or "preventive")
            by_mode[mode] = by_mode.get(mode, 0) + 1
        return {
            "count": len(items),
            "active_count": sum(1 for item in items if item["active"]),
            "candidate_count": sum(1 for item in items if item["status"] == "candidate"),
            "by_mode": by_mode,
            "rules": items,
        }

    def apply_preventive_rules(self, command: str, shell: str) -> dict[str, Any]:
        current = command.strip()
        applied: list[dict[str, Any]] = []
        for rule in self._rules.values():
            if not rule.active or rule.mode != "preventive":
                continue
            before = current
            if rule.action == "cmd_cd_to_set_location":
                current = self._repair_cmd_cd(current, shell)
            elif rule.action == "use_registry_full_path":
                current = self._use_registry_full_path(current, shell)
            if current != before:
                applied.append(
                    {
                        "rule_id": rule.rule_id,
                        "issue_code": rule.issue_code,
                        "action": rule.action,
                        "description": rule.description,
                        "before": before,
                        "after": current,
                    }
                )
        return {"command": current, "applied": applied}

    @staticmethod
    def _repair_cmd_cd(command: str, shell: str) -> str:
        if shell.strip().lower() not in {"powershell", "pwsh"}:
            return command
        match = re.match(r"^\s*cd\s+/d\s+([^;&|]+)([;&|].*)?$", command, re.IGNORECASE)
        if not match:
            return command
        raw_path = match.group(1).strip().strip('"')
        if not raw_path or any(ch in raw_path for ch in "`$\r\n"):
            return command
        remainder = match.group(2) or ""
        quoted = "'" + raw_path.replace("'", "''") + "'"
        return f"Set-Location -LiteralPath {quoted}{remainder}"

    def _use_registry_full_path(self, command: str, shell: str) -> str:
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)(\s+.*)?$", command, re.DOTALL)
        if not match:
            return command
        token = match.group(1).casefold()
        registry_name = self._KNOWN_COMMANDS.get(token)
        if not registry_name:
            return command
        resolved = self.executables.get(registry_name)
        if not resolved:
            return command
        remainder = match.group(2) or ""
        if shell.strip().lower() in {"powershell", "pwsh"}:
            return f'& "{resolved}"{remainder}'
        return command
