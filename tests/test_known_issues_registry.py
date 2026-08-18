from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from services.known_issues_registry import KnownIssuesRegistry


class KnownIssuesRegistryTests(unittest.TestCase):
    def _registry(self, rules: list[dict]) -> KnownIssuesRegistry:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "known_issues.json"
        path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
        executables = Mock()
        executables.get.side_effect = lambda name: {
            "git": r"D:\Program Files\Git\cmd\git.exe",
            "python": r"C:\Python\python.exe",
        }.get(name)
        return KnownIssuesRegistry(path, executables)

    def test_candidate_rule_never_applies(self) -> None:
        registry = self._registry([
            {
                "rule_id": "candidate",
                "issue_code": "cmd_syntax_in_powershell",
                "status": "candidate",
                "description": "candidate",
                "action": "cmd_cd_to_set_location",
                "recovery_validated": True,
                "validator_passed": True,
                "source": "test",
            }
        ])
        result = registry.apply_preventive_rules(r"cd /d D:\AIProjects; Write-Output ok", "powershell")
        self.assertEqual(result["command"], r"cd /d D:\AIProjects; Write-Output ok")
        self.assertEqual(result["applied"], [])

    def test_active_requires_recovery_and_validator(self) -> None:
        registry = self._registry([
            {
                "rule_id": "not-validated",
                "issue_code": "cmd_syntax_in_powershell",
                "status": "active",
                "description": "not validated",
                "action": "cmd_cd_to_set_location",
                "recovery_validated": False,
                "validator_passed": True,
                "source": "test",
            }
        ])
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["active_count"], 0)
        result = registry.apply_preventive_rules(r"cd /d D:\AIProjects", "powershell")
        self.assertEqual(result["applied"], [])

    def test_active_cd_rule_prevents_known_issue(self) -> None:
        registry = self._registry([
            {
                "rule_id": "cd-rule",
                "issue_code": "cmd_syntax_in_powershell",
                "status": "active",
                "description": "validated",
                "action": "cmd_cd_to_set_location",
                "recovery_validated": True,
                "validator_passed": True,
                "source": "test",
            }
        ])
        result = registry.apply_preventive_rules(r"cd /d D:\AIProjects; Write-Output ok", "powershell")
        self.assertIn("Set-Location -LiteralPath", result["command"])
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(result["applied"][0]["rule_id"], "cd-rule")

    def test_full_path_rule_uses_powershell_call_operator(self) -> None:
        registry = self._registry([
            {
                "rule_id": "path-rule",
                "issue_code": "command_not_found",
                "status": "active",
                "description": "validated",
                "action": "use_registry_full_path",
                "recovery_validated": True,
                "validator_passed": True,
                "source": "test",
            }
        ])
        result = registry.apply_preventive_rules("git status", "powershell")
        self.assertEqual(result["command"], '& "D:\\Program Files\\Git\\cmd\\git.exe" status')

    def test_full_path_rule_does_not_rewrite_cmd(self) -> None:
        registry = self._registry([
            {
                "rule_id": "path-rule",
                "issue_code": "command_not_found",
                "status": "active",
                "description": "validated for PowerShell only",
                "action": "use_registry_full_path",
                "recovery_validated": True,
                "validator_passed": True,
                "source": "test",
            }
        ])
        result = registry.apply_preventive_rules("git status", "cmd")
        self.assertEqual(result["command"], "git status")
        self.assertEqual(result["applied"], [])

    def test_candidate_promotion_requires_both_validations(self) -> None:
        registry = self._registry([])
        registry.register_candidate(
            rule_id="new-rule",
            issue_code="example",
            description="candidate",
            action="observe_only",
            source="test",
        )
        with self.assertRaises(ValueError):
            registry.promote(
                "new-rule",
                recovery_validated=True,
                validator_passed=False,
                source="validator failed",
            )
        self.assertEqual(registry.snapshot()["active_count"], 0)

    def test_candidate_can_promote_after_both_validations(self) -> None:
        registry = self._registry([])
        registry.register_candidate(
            rule_id="new-rule",
            issue_code="example",
            description="candidate",
            action="observe_only",
            source="test",
        )
        promoted = registry.promote(
            "new-rule",
            recovery_validated=True,
            validator_passed=True,
            source="integration validator passed",
        )
        self.assertTrue(promoted.active)
        self.assertEqual(registry.snapshot()["active_count"], 1)

    def test_classify_only_rule_never_rewrites_command(self) -> None:
        registry = self._registry([
            {
                "rule_id": "classify-only",
                "issue_code": "timeout",
                "status": "active",
                "description": "classification policy",
                "action": "terminate_tree_no_retry",
                "recovery_validated": True,
                "validator_passed": True,
                "source": "test",
                "mode": "classify_only",
            }
        ])
        result = registry.apply_preventive_rules("git status", "powershell")
        self.assertEqual(result["command"], "git status")
        self.assertEqual(result["applied"], [])
        self.assertEqual(registry.snapshot()["by_mode"]["classify_only"], 1)


if __name__ == "__main__":
    unittest.main()
