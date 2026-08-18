from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ExecutableInfo:
    name: str
    path: str | None
    source: str

    @property
    def available(self) -> bool:
        return bool(self.path)


class ExecutableRegistry:
    """Resolve executable paths once at startup and reuse the frozen snapshot."""

    DEFAULT_NAMES = ("python", "uv", "git", "node", "pwsh", "powershell", "cmd", "bash", "codex")

    def __init__(self, names: Iterable[str] | None = None) -> None:
        requested = tuple(dict.fromkeys(str(name).strip().lower() for name in (names or self.DEFAULT_NAMES) if str(name).strip()))
        self._items: dict[str, ExecutableInfo] = {name: self._resolve(name) for name in requested}

    @staticmethod
    def _normalize(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return str(Path(path).resolve())
        except OSError:
            return os.path.abspath(path)

    def _resolve(self, name: str) -> ExecutableInfo:
        if name == "python":
            current = self._normalize(sys.executable)
            if current and Path(current).is_file():
                return ExecutableInfo(name=name, path=current, source="sys.executable")

        if name == "cmd":
            comspec = self._normalize(os.environ.get("COMSPEC"))
            if comspec and Path(comspec).is_file():
                return ExecutableInfo(name=name, path=comspec, source="COMSPEC")

        if name == "bash" and os.name == "nt":
            git = self._normalize(shutil.which("git"))
            if git:
                git_root = Path(git).parent.parent
                for candidate in (git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"):
                    if candidate.is_file():
                        return ExecutableInfo(name=name, path=str(candidate.resolve()), source="git_install")
            # Windows' system bash.exe may only be a WSL launcher with no installed distro.
            # Treat Bash as optional unless a concrete Git Bash runtime is discoverable.
            return ExecutableInfo(name=name, path=None, source="not_found")

        resolved = self._normalize(shutil.which(name))
        return ExecutableInfo(name=name, path=resolved, source="PATH" if resolved else "not_found")

    def get(self, name: str) -> str | None:
        key = name.strip().lower()
        item = self._items.get(key)
        return item.path if item else None

    def require(self, name: str) -> str:
        path = self.get(name)
        if not path:
            raise RuntimeError(f"Executable was not found at A0 startup: {name}")
        return path

    def preferred_powershell(self, *, prefer_pwsh: bool = True) -> str | None:
        order = ("pwsh", "powershell") if prefer_pwsh else ("powershell", "pwsh")
        for name in order:
            path = self.get(name)
            if path:
                return path
        return None

    def snapshot(self) -> dict[str, dict[str, str | bool | None]]:
        return {
            name: {
                "available": item.available,
                "path": item.path,
                "source": item.source,
            }
            for name, item in self._items.items()
        }
