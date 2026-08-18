from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.error_recovery import ErrorClassifier, RecoveryEngine


class ErrorRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = Mock()
        self.registry.get.side_effect = lambda name: {
            "git": r"D:\Program Files\Git\cmd\git.exe",
            "python": r"C:\Python\python.exe",
        }.get(name)
        self.engine = RecoveryEngine(self.registry)
        self.classifier = ErrorClassifier()

    def test_classifies_timeout_as_non_retryable(self) -> None:
        result = self.classifier.classify({"ok": False, "timed_out": True, "status": "timeout"})
        self.assertEqual(result.code, "timeout")
        self.assertFalse(result.retryable)
        self.assertEqual(result.confidence, "high")

    def test_classifies_command_not_found_as_retryable(self) -> None:
        result = self.classifier.classify({
            "ok": False,
            "timed_out": False,
            "stderr": "'git' is not recognized as an internal or external command",
        })
        self.assertEqual(result.code, "command_not_found")
        self.assertTrue(result.retryable)

    def test_repairs_cmd_cd_for_powershell(self) -> None:
        repair = self.engine.repair_preflight({
            "shell": "powershell",
            "command": r"cd /d D:\AIProjects; Write-Output ok",
            "issues": [{"code": "cmd_syntax_in_powershell", "severity": "warning"}],
        })
        self.assertIsNotNone(repair)
        self.assertIn("Set-Location -LiteralPath 'D:\\AIProjects'", repair["repaired_command"])
        self.assertIn("Write-Output ok", repair["repaired_command"])

    def test_does_not_repair_ambiguous_cd_path(self) -> None:
        repair = self.engine.repair_preflight({
            "shell": "powershell",
            "command": r"cd /d $env:TEMP; Write-Output ok",
            "issues": [{"code": "cmd_syntax_in_powershell", "severity": "warning"}],
        })
        self.assertIsNone(repair)

    def test_replaces_known_command_with_registry_path(self) -> None:
        repair = self.engine.repair_command_not_found("git status --short")
        self.assertIsNotNone(repair)
        self.assertEqual(
            repair["repaired_command"],
            '"D:\\Program Files\\Git\\cmd\\git.exe" status --short',
        )

    def test_unknown_command_is_not_repaired(self) -> None:
        self.assertIsNone(self.engine.repair_command_not_found("mystery-tool --version"))


if __name__ == "__main__":
    unittest.main()
