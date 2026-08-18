from __future__ import annotations

import unittest
from unittest.mock import patch

from services.executable_registry import ExecutableRegistry


class ExecutableRegistryTests(unittest.TestCase):
    @patch("services.executable_registry.shutil.which")
    @patch("services.executable_registry.sys.executable", r"C:\Python313\python.exe")
    @patch("services.executable_registry.Path.is_file", return_value=True)
    def test_resolves_and_freezes_startup_paths(self, _is_file, which) -> None:
        values = {
            "git": r"D:\Program Files\Git\cmd\git.exe",
            "pwsh": r"C:\Program Files\PowerShell\7\pwsh.exe",
            "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "node": r"C:\Program Files\nodejs\node.exe",
            "uv": r"C:\Users\u\.local\bin\uv.exe",
            "codex": r"C:\Users\u\AppData\Roaming\npm\codex.cmd",
            "cmd": r"C:\Windows\System32\cmd.exe",
        }
        which.side_effect = values.get

        registry = ExecutableRegistry(("python", "git", "pwsh", "powershell", "node", "uv", "codex"))
        first_git = registry.get("git")
        values["git"] = r"Z:\changed\git.exe"

        self.assertEqual(registry.get("git"), first_git)
        self.assertEqual(registry.preferred_powershell(), registry.get("pwsh"))
        self.assertTrue(registry.snapshot()["python"]["available"])

    @patch("services.executable_registry.shutil.which")
    @patch("services.executable_registry.Path.is_file", return_value=True)
    def test_windows_bash_prefers_git_install_over_system_launcher(self, _is_file, which) -> None:
        which.side_effect = lambda name: r"D:\\Program Files\\Git\\cmd\\git.exe" if name == "git" else None

        registry = ExecutableRegistry(("bash",))

        self.assertTrue(registry.get("bash").lower().endswith(r"git\bin\bash.exe"))
        self.assertEqual(registry.snapshot()["bash"]["source"], "git_install")

    @patch("services.executable_registry.shutil.which", return_value=None)
    @patch("services.executable_registry.Path.is_file", return_value=False)
    def test_missing_executable_is_recorded(self, _is_file, _which) -> None:
        registry = ExecutableRegistry(("git",))
        self.assertIsNone(registry.get("git"))
        self.assertEqual(registry.snapshot()["git"]["source"], "not_found")
        with self.assertRaises(RuntimeError):
            registry.require("git")


if __name__ == "__main__":
    unittest.main()
