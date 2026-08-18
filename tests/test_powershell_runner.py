from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.powershell_runner import PowerShellRunner


class PowerShellRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process_service = Mock()
        self.process_service.run.return_value = {
            "ok": True,
            "pid": 4321,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "timed_out": False,
        }
        self.executables = Mock()
        self.executables.preferred_powershell.return_value = r"C:\Program Files\PowerShell\7\pwsh.exe"
        self.runner = PowerShellRunner(self.process_service, self.executables)

    def test_standard_flags_utf8_and_timeout(self) -> None:
        result = self.runner.run("Write-Output '中文'", timeout_seconds=12)

        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 4321)
        command = self.process_service.run.call_args.args[0]
        self.assertEqual(command[0], r"C:\Program Files\PowerShell\7\pwsh.exe")
        self.assertIn("-NoProfile", command)
        self.assertIn("-NonInteractive", command)
        self.assertIn("-ExecutionPolicy", command)
        self.assertIn("Bypass", command)
        self.assertIn("[Console]::OutputEncoding", command[-1])
        self.assertIn("Write-Output '中文'", command[-1])
        self.assertEqual(self.process_service.run.call_args.kwargs["timeout_seconds"], 12)
        env = self.process_service.run.call_args.kwargs["env"]
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_uses_frozen_registry_powershell(self) -> None:
        self.runner.run("$PSVersionTable.PSVersion.ToString()")
        self.executables.preferred_powershell.assert_called_once_with(prefer_pwsh=True)
        self.assertEqual(self.process_service.run.call_args.args[0][0], r"C:\Program Files\PowerShell\7\pwsh.exe")

    def test_custom_environment_is_preserved_and_utf8_defaults_added(self) -> None:
        env = {"A0_TEST": "yes"}
        self.runner.run("Write-Output $env:A0_TEST", executable=r"C:\pwsh.exe", env=env)

        passed = self.process_service.run.call_args.kwargs["env"]
        self.assertEqual(passed["A0_TEST"], "yes")
        self.assertEqual(passed["PYTHONUTF8"], "1")
        self.assertEqual(passed["PYTHONIOENCODING"], "utf-8")

    def test_rejects_missing_working_directory(self) -> None:
        result = self.runner.run("Write-Output ok", cwd=r"Z:\definitely-not-present\a0-ps-runner")
        self.assertFalse(result["ok"])
        self.process_service.run.assert_not_called()

    def test_reports_missing_powershell(self) -> None:
        self.executables.preferred_powershell.return_value = None
        result = self.runner.run("Write-Output ok")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["message"])
        self.process_service.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
