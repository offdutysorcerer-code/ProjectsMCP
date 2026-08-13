from __future__ import annotations

import locale
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


class ProcessService:
    """Run child processes with bounded output, timeouts, and tree cleanup."""

    def __init__(
        self,
        default_timeout_seconds: int = 60,
        max_output_bytes: int = 2 * 1024 * 1024,
        kill_grace_seconds: int = 3,
    ) -> None:
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))
        self.max_output_bytes = max(4096, int(max_output_bytes))
        self.kill_grace_seconds = max(1, int(kill_grace_seconds))

    @staticmethod
    def _decode(data: bytes) -> str:
        for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "cp950", "cp437"):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _normalized_environment(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
        if os.name != "nt":
            return dict(env) if env is not None else None

        normalized = dict(os.environ if env is None else env)
        system_root = normalized.get("SystemRoot") or normalized.get("WINDIR") or r"C:\Windows"
        user_profile = normalized.get("USERPROFILE") or str(Path.home())
        temp_candidate = (normalized.get("TEMP") or "").strip().strip('"')
        temp_dir = temp_candidate if temp_candidate and Path(temp_candidate).is_dir() else str(Path(user_profile) / "AppData" / "Local" / "Temp")
        user_path = Path(user_profile)
        user_drive = user_path.drive or "C:"

        defaults = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "ComSpec": str(Path(system_root) / "System32" / "cmd.exe"),
            "ProgramFiles": r"C:\Program Files",
            "ProgramFiles(x86)": r"C:\Program Files (x86)",
            "ProgramW6432": r"C:\Program Files",
            "USERPROFILE": user_profile,
            "HOME": user_profile,
            "HOMEDRIVE": user_drive,
            "HOMEPATH": str(user_path).replace(user_drive, "", 1),
            "TEMP": temp_dir,
            "TMP": temp_dir,
        }
        for key, value in defaults.items():
            current = (normalized.get(key) or "").strip().strip('"')
            if not current or (key in {"TEMP", "TMP"} and not Path(current).is_dir()):
                normalized[key] = value
        return normalized

    def _read_output(self, stream: Any) -> tuple[str, bool]:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        truncated = size > self.max_output_bytes
        stream.seek(max(0, size - self.max_output_bytes))
        data = stream.read()
        text = self._decode(data).strip()
        if truncated:
            text = f"[output truncated; showing last {self.max_output_bytes} bytes]\n{text}"
        return text, truncated

    def _terminate_tree(self, process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.kill_grace_seconds,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=self.kill_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = self.default_timeout_seconds if timeout_seconds is None else max(1, int(timeout_seconds))
        command_list = [str(part) for part in command]
        started = time.monotonic()
        creationflags = 0
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    command_list,
                    cwd=str(cwd) if cwd else None,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=self._normalized_environment(env),
                    shell=False,
                    creationflags=creationflags,
                    **popen_kwargs,
                )
            except OSError as exc:
                return {
                    "ok": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": f"Unable to start process: {exc}",
                    "timed_out": False,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "command": command_list,
                }

            timed_out = False
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_tree(process)
                returncode = process.poll()

            stdout, stdout_truncated = self._read_output(stdout_file)
            stderr, stderr_truncated = self._read_output(stderr_file)

        if timed_out:
            message = f"Command timed out after {timeout} seconds; process tree was terminated."
            stderr = f"{stderr}\n{message}".strip()

        return {
            "ok": returncode == 0 and not timed_out,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "timeout_seconds": timeout,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output_truncated": stdout_truncated or stderr_truncated,
            "command": command_list,
        }
