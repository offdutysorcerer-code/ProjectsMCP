from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from services.file_service import FileService
from services.process_service import ProcessService


class LocalAgentService:
    """Dispatch narrowly-scoped coding tasks to the A28 LM Studio worker."""

    def __init__(
        self,
        file_service: FileService,
        process_service: ProcessService,
        worker_dir: Path,
        timeout_seconds: int = 180,
    ) -> None:
        self.file_service = file_service
        self.process_service = process_service
        self.worker_dir = worker_dir.resolve()
        self.worker_script = self.worker_dir / "local-coding-worker.ps1"
        self.token_file = self.worker_dir / "token.txt"
        self.tasks_dir = self.worker_dir / "tasks"
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "ok": self.worker_script.is_file() and self.token_file.is_file(),
            "backend": "lmstudio",
            "agent": "LocalDeveloper",
            "worker_dir": str(self.worker_dir),
            "worker_script": str(self.worker_script),
            "worker_exists": self.worker_script.is_file(),
            "token_exists": self.token_file.is_file(),
        }

    def run_task(
        self,
        *,
        project: str,
        source_path: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str] | None = None,
        task_id: str = "",
        max_changed_lines: int = 80,
        validation_command: str = "",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        project = project.strip()
        source_path = source_path.strip().replace("\\", "/")
        objective = objective.strip()
        if not project:
            raise ValueError("project must not be empty")
        if not source_path:
            raise ValueError("source_path must not be empty")
        if not objective:
            raise ValueError("objective must not be empty")
        criteria = [str(x).strip() for x in acceptance_criteria if str(x).strip()]
        if not criteria:
            raise ValueError("acceptance_criteria must contain at least one item")

        source_file = self.file_service.resolve_project_path(project, source_path)
        if not source_file.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        if not self.worker_script.is_file():
            raise FileNotFoundError(f"Local coding worker not found: {self.worker_script}")
        if not self.token_file.is_file():
            raise FileNotFoundError(f"LM Studio token file not found: {self.token_file}")

        normalized_task_id = self._task_id(task_id or f"local-{uuid.uuid4().hex[:12]}")
        task_file = self.tasks_dir / f"{normalized_task_id}.json"
        payload = {
            "task_id": normalized_task_id,
            "source_file": str(source_file),
            "objective": objective,
            "acceptance_criteria": criteria,
            "constraints": [str(x).strip() for x in (constraints or []) if str(x).strip()],
            "max_changed_lines": max(1, int(max_changed_lines)),
            "validation_command": validation_command.strip(),
        }
        # Windows PowerShell 5.1 treats BOM-less UTF-8 as the active ANSI code page.
        # Write task JSON with a UTF-8 BOM so non-ASCII paths/prompts survive Get-Content.
        task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")

        timeout = self.timeout_seconds if timeout_seconds is None else max(10, int(timeout_seconds))
        run = self.process_service.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.worker_script),
                "-TaskFile",
                str(task_file),
            ],
            cwd=self.worker_dir,
            timeout_seconds=timeout,
        )
        if not run.get("ok"):
            return {
                "ok": False,
                "status": "worker_failed",
                "agent": "LocalDeveloper",
                "task_id": normalized_task_id,
                "task_file": str(task_file),
                "process": run,
            }

        stdout = str(run.get("stdout") or "").strip()
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "status": "invalid_worker_output",
                "agent": "LocalDeveloper",
                "task_id": normalized_task_id,
                "task_file": str(task_file),
                "process": run,
                "error": str(exc),
            }

        diff_file = Path(str(result.get("diff_file") or ""))
        diff_text = ""
        if diff_file.is_file():
            diff_text = diff_file.read_text(encoding="utf-8")
            if len(diff_text) > 30000:
                diff_text = diff_text[:30000] + "\n[diff truncated]"

        return {
            "ok": bool(result.get("overall_pass")),
            "status": "passed" if result.get("overall_pass") else "validation_failed",
            "agent": "LocalDeveloper",
            "task_id": normalized_task_id,
            "task_file": str(task_file),
            "result": result,
            "diff": diff_text,
        }

    @staticmethod
    def _task_id(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
        if not cleaned:
            raise ValueError("task_id is invalid")
        return cleaned[:120]
