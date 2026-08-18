from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.execution_runtime_service import ExecutionRuntimeService


class ExecutionRuntimeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process_service = Mock()
        self.process_service.run.return_value = {
            "ok": True,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "timed_out": False,
        }
        self.executables = Mock()
        self.executables.preferred_powershell.return_value = r"C:\Program Files\PowerShell\7\pwsh.exe"
        self.executables.get.side_effect = lambda name: r"C:\Windows\System32\cmd.exe" if name == "cmd" else None
        self.known_issues = Mock()
        self.known_issues.apply_preventive_rules.side_effect = lambda command, shell: {"command": command, "applied": []}
        self.runtime = ExecutionRuntimeService(self.process_service, self.executables, self.known_issues)

    def test_powershell_uses_standard_noninteractive_flags(self) -> None:
        result = self.runtime.run_shell("Write-Output 'ok'", "powershell", timeout_seconds=12)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "success")
        command = self.process_service.run.call_args.args[0]
        self.assertEqual(command[0], r"C:\Program Files\PowerShell\7\pwsh.exe")
        self.assertIn("-NoProfile", command)
        self.assertIn("-NonInteractive", command)
        self.assertIn("-ExecutionPolicy", command)
        self.assertIn("Bypass", command)
        self.assertEqual(command[-2], "-Command")
        self.assertIn("[Console]::OutputEncoding", command[-1])
        self.assertTrue(command[-1].endswith("Write-Output 'ok'"))
        self.assertEqual(self.process_service.run.call_args.kwargs["timeout_seconds"], 12)

    def test_cmd_uses_registry_path_and_safe_switches(self) -> None:
        result = self.runtime.run_shell("echo ok", "cmd")

        self.assertTrue(result["ok"])
        command = self.process_service.run.call_args.args[0]
        self.assertEqual(command, [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c", "echo ok"])

    def test_rejects_empty_command_before_process_launch(self) -> None:
        result = self.runtime.run_shell("   ", "cmd")
        self.assertFalse(result["ok"])
        self.process_service.run.assert_not_called()

    def test_rejects_unknown_shell_before_process_launch(self) -> None:
        result = self.runtime.run_shell("echo ok", "zsh")
        self.assertFalse(result["ok"])
        self.assertIn("shell must be", result["message"])
        self.process_service.run.assert_not_called()

    def test_rejects_missing_working_directory(self) -> None:
        result = self.runtime.run_shell("echo ok", "cmd", cwd=r"Z:\definitely-not-present\a0-runtime-test")
        self.assertFalse(result["ok"])
        self.assertIn("Working directory not found", result["message"])
        self.process_service.run.assert_not_called()

    def test_preflight_repair_converts_cmd_cd_before_execution(self) -> None:
        result = self.runtime.run_shell(r"cd /d D:\AIProjects; Write-Output ok", "powershell")

        self.assertTrue(result["ok"])
        self.assertTrue(result["recovery"]["attempted"])
        self.assertEqual(result["recovery"]["retry_count"], 0)
        command = self.process_service.run.call_args.args[0][-1]
        self.assertIn("Set-Location -LiteralPath 'D:\\AIProjects'", command)
        self.assertNotIn("cd /d", command.lower())

    def test_command_not_found_retries_once_with_registry_path(self) -> None:
        self.executables.get.side_effect = lambda name: {
            "cmd": r"C:\Windows\System32\cmd.exe",
            "git": r"D:\Program Files\Git\cmd\git.exe",
        }.get(name)
        self.process_service.run.side_effect = [
            {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "'git' is not recognized as an internal or external command",
                "timed_out": False,
            },
            {
                "ok": True,
                "returncode": 0,
                "stdout": "ok",
                "stderr": "",
                "timed_out": False,
            },
        ]

        result = self.runtime.run_shell("git status", "cmd")

        self.assertTrue(result["ok"])
        self.assertEqual(self.process_service.run.call_count, 2)
        self.assertEqual(result["recovery"]["retry_count"], 1)
        retry_command = self.process_service.run.call_args_list[1].args[0][-1]
        self.assertIn(r'"D:\Program Files\Git\cmd\git.exe" status', retry_command)
        self.assertEqual(result["classification"]["code"], "success")
        self.assertEqual(result["first_attempt"]["classification"]["code"], "command_not_found")

    def test_bash_uses_optional_registry_runner(self) -> None:
        self.executables.get.side_effect = lambda name: {
            "cmd": r"C:\\Windows\\System32\\cmd.exe",
            "bash": r"C:\\Program Files\\Git\\bin\\bash.exe",
        }.get(name)

        result = self.runtime.run_shell("printf 'ok\\n'", "bash", timeout_seconds=7)

        self.assertTrue(result["ok"])
        self.assertEqual(result["shell"], "bash")
        self.assertEqual(
            self.process_service.run.call_args.args[0],
            [r"C:\\Program Files\\Git\\bin\\bash.exe", "-lc", "printf 'ok\\n'"],
        )
        self.assertEqual(self.process_service.run.call_args.kwargs["timeout_seconds"], 7)

    def test_timeout_is_not_retried(self) -> None:
        self.process_service.run.return_value = {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "Command timed out",
            "timed_out": True,
        }

        result = self.runtime.run_shell("echo ok", "cmd", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"]["code"], "timeout")
        self.assertEqual(result["recovery"]["retry_count"], 0)
        self.assertEqual(self.process_service.run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
