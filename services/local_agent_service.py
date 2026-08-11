from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
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
        max_concurrent_jobs: int = 4,
    ) -> None:
        self.file_service = file_service
        self.process_service = process_service
        self.worker_dir = worker_dir.resolve()
        self.worker_script = self.worker_dir / "local-coding-worker.ps1"
        self.token_file = self.worker_dir / "token.txt"
        self.tasks_dir = self.worker_dir / "tasks"
        self.results_dir = self.tasks_dir / "results"
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.max_concurrent_jobs = max(1, int(max_concurrent_jobs))
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_jobs,
            thread_name_prefix="local-agent",
        )
        self._jobs: dict[str, Future[dict[str, Any]]] = {}
        self._jobs_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        with self._jobs_lock:
            active_jobs = sum(1 for future in self._jobs.values() if not future.done())
        return {
            "ok": self.worker_script.is_file() and self.token_file.is_file(),
            "backend": "lmstudio",
            "agent": "LocalDeveloper",
            "worker_dir": str(self.worker_dir),
            "worker_script": str(self.worker_script),
            "worker_exists": self.worker_script.is_file(),
            "token_exists": self.token_file.is_file(),
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "active_jobs": active_jobs,
        }

    def submit_task(
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
        normalized_task_id = self._task_id(task_id or f"local-{uuid.uuid4().hex[:12]}")
        with self._jobs_lock:
            existing = self._jobs.get(normalized_task_id)
            if existing is not None and not existing.done():
                raise ValueError(f"Local agent task is already active: {normalized_task_id}")

            future = self._executor.submit(
                self.run_task,
                project=project,
                source_path=source_path,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                constraints=constraints,
                task_id=normalized_task_id,
                max_changed_lines=max_changed_lines,
                validation_command=validation_command,
                timeout_seconds=timeout_seconds,
            )
            self._jobs[normalized_task_id] = future
            future.add_done_callback(
                lambda completed, tid=normalized_task_id: self._persist_future_result(tid, completed)
            )

        return {
            "ok": True,
            "status": "queued",
            "agent": "LocalDeveloper",
            "task_id": normalized_task_id,
            "max_concurrent_jobs": self.max_concurrent_jobs,
        }

    def task_status(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = self._task_id(task_id)
        with self._jobs_lock:
            future = self._jobs.get(normalized_task_id)

        if future is not None:
            if future.cancelled():
                return {"ok": False, "status": "cancelled", "task_id": normalized_task_id}
            if not future.done():
                return {
                    "ok": True,
                    "status": "running" if future.running() else "queued",
                    "task_id": normalized_task_id,
                }
            result = self._future_result(future, normalized_task_id)
            return {
                "ok": bool(result.get("ok")),
                "status": str(result.get("status") or "completed"),
                "task_id": normalized_task_id,
            }

        persisted = self._read_persisted_result(normalized_task_id)
        if persisted is not None:
            return {
                "ok": bool(persisted.get("ok")),
                "status": str(persisted.get("status") or "completed"),
                "task_id": normalized_task_id,
                "persisted": True,
            }
        return {"ok": False, "status": "not_found", "task_id": normalized_task_id}

    def task_result(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = self._task_id(task_id)
        with self._jobs_lock:
            future = self._jobs.get(normalized_task_id)

        if future is not None:
            if not future.done():
                return {
                    "ok": True,
                    "status": "running" if future.running() else "queued",
                    "task_id": normalized_task_id,
                    "result_ready": False,
                }
            result = self._future_result(future, normalized_task_id)
            return {**result, "result_ready": True}

        persisted = self._read_persisted_result(normalized_task_id)
        if persisted is not None:
            return {**persisted, "result_ready": True, "persisted": True}
        return {
            "ok": False,
            "status": "not_found",
            "task_id": normalized_task_id,
            "result_ready": False,
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

    def _persist_future_result(self, task_id: str, future: Future[dict[str, Any]]) -> None:
        result = self._future_result(future, task_id)
        result_file = self.results_dir / f"{task_id}.json"
        temp = result_file.with_suffix(".json.tmp")
        try:
            temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(result_file)
        except OSError:
            pass

    @staticmethod
    def _future_result(future: Future[dict[str, Any]], task_id: str) -> dict[str, Any]:
        try:
            return future.result()
        except Exception as exc:
            return {
                "ok": False,
                "status": "internal_error",
                "agent": "LocalDeveloper",
                "task_id": task_id,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _read_persisted_result(self, task_id: str) -> dict[str, Any] | None:
        result_file = self.results_dir / f"{task_id}.json"
        if not result_file.is_file():
            return None
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _task_id(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
        if not cleaned:
            raise ValueError("task_id is invalid")
        return cleaned[:120]
