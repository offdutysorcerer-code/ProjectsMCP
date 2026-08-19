from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.command_preflight import CommandPreflightChecker


class CommandPreflightCheckerTests(unittest.TestCase):
    def _registry(self, *, pwsh: str | None = r"C:\pwsh.exe", powershell: str | None = None, cmd: str | None = r"C:\cmd.exe") -> Mock:
        registry = Mock()
        registry.get.side_effect = lambda name: {"cmd": cmd, "pwsh": pwsh, "powershell": powershell}.get(name)
        registry.preferred_powershell.side_effect = lambda prefer_pwsh=True: pwsh or powershell
        return registry

    def test_rejects_missing_working_directory(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check("Write-Output ok", "powershell", cwd=r"Z:\not-present\preflight")
        self.assertFalse(result["ok"])
        self.assertIn("missing_cwd", [x["code"] for x in result["issues"]])

    def test_rejects_nul_character(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check("Write-Output ok\x00", "powershell")
        self.assertFalse(result["ok"])
        self.assertIn("nul_character", [x["code"] for x in result["issues"]])

    def test_warns_cmd_syntax_inside_powershell(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check("cd /d D:\\AIProjects; Write-Output ok", "powershell")
        self.assertTrue(result["ok"])
        self.assertIn("cmd_syntax_in_powershell", [x["code"] for x in result["issues"]])

    def test_warns_powershell_syntax_inside_cmd(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check("echo $env:PATH", "cmd")
        self.assertTrue(result["ok"])
        self.assertIn("powershell_syntax_in_cmd", [x["code"] for x in result["issues"]])

    def test_blocks_ps7_only_parallel_on_windows_powershell(self) -> None:
        checker = CommandPreflightChecker(self._registry(pwsh=None, powershell=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"))
        result = checker.check("1..3 | ForEach-Object -Parallel { $_ }", "powershell")
        self.assertFalse(result["ok"])
        self.assertIn("powershell_version_incompatible", [x["code"] for x in result["issues"]])

    def test_normalizes_utf8_environment_for_powershell(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check("Write-Output ok", "powershell", env={"A0_TEST": "1"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["env"]["A0_TEST"], "1")
        self.assertEqual(result["env"]["PYTHONUTF8"], "1")
        self.assertEqual(result["env"]["PYTHONIOENCODING"], "utf-8")

    def test_blocks_known_external_command_missing_from_registry(self) -> None:
        registry = self._registry()
        registry.get.side_effect = lambda name: {"cmd": r"C:\\cmd.exe", "git": None}.get(name)
        checker = CommandPreflightChecker(registry)
        result = checker.check("git status", "cmd")
        self.assertFalse(result["ok"])
        self.assertIn("missing_command", [x["code"] for x in result["issues"]])

    def test_accepts_optional_bash_when_registered(self) -> None:
        registry = self._registry()
        registry.get.side_effect = lambda name: {
            "cmd": r"C:\\cmd.exe",
            "pwsh": r"C:\\pwsh.exe",
            "bash": r"C:\\Program Files\\Git\\bin\\bash.exe",
        }.get(name)
        checker = CommandPreflightChecker(registry)
        result = checker.check("printf ok", "bash", env={"A0_TEST": "1"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["executable"], r"C:\\Program Files\\Git\\bin\\bash.exe")
        self.assertEqual(result["env"]["PYTHONUTF8"], "1")

    def test_blocks_large_inline_source_patch_and_guides_to_fileservice(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        command = (
            "$p='agent.ps1';$s=[IO.File]::ReadAllText($p);"
            "$s=$s.Replace('old','new');$start=$s.IndexOf('function Start-App');"
            "$s=$s.Substring(0,$start)+'replacement';"
            "[IO.File]::WriteAllText($p,$s);Start-Process pwsh -WindowStyle Hidden;"
            + ("# padding for representative long inline patch\n" * 40)
        )
        result = checker.check(command, "powershell")
        self.assertFalse(result["ok"])
        issue = next(x for x in result["issues"] if x["code"] == "prefer_structured_file_edit")
        self.assertIn("FileService", issue["message"])
        self.assertIn("replace_text", issue["message"])

    def test_does_not_block_normal_powershell_process_or_small_file_edit(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        normal = checker.check("Start-Process notepad.exe", "powershell")
        small_edit = checker.check("$s='abc'; $s=$s.Replace('a','b'); Write-Output $s", "powershell")
        self.assertTrue(normal["ok"])
        self.assertTrue(small_edit["ok"])
        self.assertNotIn("prefer_structured_file_edit", [x["code"] for x in normal["issues"]])
        self.assertNotIn("prefer_structured_file_edit", [x["code"] for x in small_edit["issues"]])

    def test_warns_long_ambiguous_inline_rewrite_without_source_target(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        command = (
            "$s=[IO.File]::ReadAllText($p);$s=$s.Replace('a','b');"
            "$s=$s.Substring(0,$s.IndexOf('marker'));" + ("Write-Output 'padding';" * 45)
        )
        result = checker.check(command, "powershell")
        self.assertTrue(result["ok"])
        self.assertIn("powershell_inline_patch_risk", [x["code"] for x in result["issues"]])

    def test_blocks_missing_import_module_path(self) -> None:
        checker = CommandPreflightChecker(self._registry())
        result = checker.check(r"Import-Module Z:\\missing\\Nope.psm1", "powershell")
        self.assertFalse(result["ok"])
        self.assertIn("missing_module_path", [x["code"] for x in result["issues"]])


if __name__ == "__main__":
    unittest.main()
