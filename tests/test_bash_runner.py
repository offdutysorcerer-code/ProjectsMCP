from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.bash_runner import BashRunner


class BashRunnerTests(unittest.TestCase):
    def test_uses_login_command_mode_and_registry_path(self) -> None:
        process_service = Mock()
        process_service.run.return_value = {
            "ok": True,
            "returncode": 0,
            "stdout": "ok\n",
            "stderr": "",
            "timed_out": False,
        }
        executables = Mock()
        executables.get.return_value = r"C:\Program Files\Git\bin\bash.exe"
        runner = BashRunner(process_service, executables)

        result = runner.run("printf 'ok\\n'", timeout_seconds=9)

        self.assertTrue(result["ok"])
        self.assertEqual(result["shell"], "bash")
        self.assertEqual(
            process_service.run.call_args.args[0],
            [r"C:\Program Files\Git\bin\bash.exe", "-lc", "printf 'ok\\n'"],
        )
        self.assertEqual(process_service.run.call_args.kwargs["timeout_seconds"], 9)
        self.assertEqual(process_service.run.call_args.kwargs["env"]["PYTHONUTF8"], "1")

    def test_missing_bash_is_nonfatal_until_requested(self) -> None:
        process_service = Mock()
        executables = Mock()
        executables.get.return_value = None
        runner = BashRunner(process_service, executables)

        result = runner.run("echo ok")

        self.assertFalse(result["ok"])
        self.assertIn("not available", result["message"])
        process_service.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
