from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path
from typing import Any


class DesktopService:
    """Windows desktop mouse control and visible cursor-highlight overlay."""

    def __init__(self, overlay_script: Path) -> None:
        self.overlay_script = overlay_script.resolve()
        self._overlay_process: subprocess.Popen[str] | None = None

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Desktop mouse control is only supported on Windows.")

    def overlay_status(self) -> dict[str, Any]:
        process = self._overlay_process
        running = process is not None and process.poll() is None
        if process is not None and not running:
            self._overlay_process = None
        return {
            "ok": True,
            "running": running,
            "pid": process.pid if running and process is not None else None,
            "script": str(self.overlay_script),
        }

    def start_overlay(self, color: str = "#00E5FF", size: int = 64) -> dict[str, Any]:
        self._require_windows()
        status = self.overlay_status()
        if status["running"]:
            return {**status, "message": "Mouse highlight overlay is already running."}
        if not self.overlay_script.is_file():
            return {"ok": False, "running": False, "message": f"Overlay script not found: {self.overlay_script}"}

        size = max(24, min(int(size), 240))
        powershell = "powershell.exe"
        command = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-STA",
            "-File",
            str(self.overlay_script),
            "-Color",
            color,
            "-Size",
            str(size),
        ]
        try:
            self._overlay_process = subprocess.Popen(
                command,
                cwd=str(self.overlay_script.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
            )
        except FileNotFoundError:
            command[0] = "pwsh.exe"
            self._overlay_process = subprocess.Popen(
                command,
                cwd=str(self.overlay_script.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
            )
        return {**self.overlay_status(), "message": "Mouse highlight overlay started."}

    def stop_overlay(self) -> dict[str, Any]:
        process = self._overlay_process
        if process is None or process.poll() is not None:
            self._overlay_process = None
            return {"ok": True, "running": False, "message": "Mouse highlight overlay is not running."}
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        self._overlay_process = None
        return {"ok": True, "running": False, "message": "Mouse highlight overlay stopped."}

    def get_mouse_position(self) -> dict[str, Any]:
        self._require_windows()

        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        point = Point()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return {"ok": False, "message": "GetCursorPos failed."}
        return {"ok": True, "x": point.x, "y": point.y}

    def move_mouse(self, x: int, y: int) -> dict[str, Any]:
        self._require_windows()
        if not ctypes.windll.user32.SetCursorPos(int(x), int(y)):
            return {"ok": False, "message": "SetCursorPos failed."}
        return {"ok": True, "x": int(x), "y": int(y)}

    def click_mouse(self, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        self._require_windows()
        normalized = button.strip().lower()
        flags = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }
        if normalized not in flags:
            return {"ok": False, "message": "button must be left, right, or middle."}
        clicks = max(1, min(int(clicks), 3))
        down, up = flags[normalized]
        for _ in range(clicks):
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
        return {"ok": True, "button": normalized, "clicks": clicks, **self.get_mouse_position()}
