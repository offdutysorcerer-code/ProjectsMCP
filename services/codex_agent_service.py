from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.executable_registry import ExecutableRegistry
from services.file_service import FileService
from services.process_service import ProcessService


class CodexAgentService:
    """Dispatch coding tasks to the real OpenAI Codex CLI."""

    _ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
    _MAX_TIMEOUT_SECONDS = 3600
    _MAX_OBJECTIVE_CHARS = 12000
    _MAX_CRITERIA_ITEMS = 50
    _MAX_CONSTRAINT_ITEMS = 50
    _MAX_ITEM_CHARS = 4000

    def __init__(
        self,
        file_service: FileService,
        process_service: ProcessService,
        executable: str = "codex",
        timeout_seconds: int = 900,
        max_concurrent_jobs: int = 2,
        telemetry: Any | None = None,
        executables: ExecutableRegistry | None = None,
    ) -> None:
        self.file_service = file_service
        self.process_service = process_service
        self.executables = executables
        self.executable = executable.strip() or "codex"
        self.timeout_seconds = max(30, int(timeout_seconds))
        self.max_concurrent_jobs = max(1, int(max_concurrent_jobs))
        self.telemetry = telemetry
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_jobs,
            thread_name_prefix="codex-agent",
        )
        self._jobs: dict[str, Future[dict[str, Any]]] = {}
        self._jobs_lock = threading.Lock()
        self._run_slots = threading.BoundedSemaphore(self.max_concurrent_jobs)

    def _resolved_executable(self) -> str | None:
        candidate = Path(self.executable)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate.resolve())
        if self.executables is not None:
            return self.executables.get(self.executable)
        return shutil.which(self.executable)

    def status(self) -> dict[str, Any]:
        resolved = self._resolved_executable()
        result: dict[str, Any] = {
            "ok": bool(resolved),
            "backend": "openai-codex-cli",
            "agent": "Codex",
            "configured_executable": self.executable,
            "resolved_executable": resolved,
            "max_concurrent_jobs": self.max_concurrent_jobs,
        }
        if not resolved:
            result["status"] = "cli_not_found"
            result["hint"] = "Install the official Codex CLI, then run `codex` once and sign in with ChatGPT."
            return result

        version = self.process_service.run(
            [resolved, "--version"],
            cwd=Path.cwd(),
            timeout_seconds=15,
        )
        auth = self.process_service.run(
            [resolved, "login", "status"],
            cwd=Path.cwd(),
            timeout_seconds=20,
        )
        auth_text = "\n".join(
            part.strip() for part in [str(auth.get("stdout") or ""), str(auth.get("stderr") or "")] if part.strip()
        )
        result.update(
            {
                "version": str(version.get("stdout") or version.get("stderr") or "").strip(),
                "auth_ok": bool(auth.get("ok")) and "Not logged in" not in auth_text,
                "auth_status": auth_text,
                "status": "ready" if version.get("ok") and auth.get("ok") and "Not logged in" not in auth_text else "needs_attention",
            }
        )
        result["ok"] = result["status"] == "ready"
        return result

    def submit_task(
        self,
        *,
        project: str,
        working_path: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str] | None = None,
        task_id: str = "",
        sandbox: str = "workspace-write",
        model: str = "",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        normalized_task_id = self._task_id(task_id or f"codex-{uuid.uuid4().hex[:12]}")
        self._validate_request(objective, acceptance_criteria, constraints or [], timeout_seconds)
        with self._jobs_lock:
            existing = self._jobs.get(normalized_task_id)
            if existing is not None and not existing.done():
                raise ValueError(f"Codex task is already active: {normalized_task_id}")
            self._emit(
                "task.queued",
                task_id=normalized_task_id,
                agent_id="codex",
                data={
                    "title": objective[:120],
                    "objective": objective,
                    "project": project,
                    "workingPath": working_path,
                    "assignedTo": "codex",
                    "backend": "openai-codex-cli",
                    "queuedAt": self._now(),
                },
            )
            future = self._executor.submit(
                self.run_task,
                project=project,
                working_path=working_path,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                constraints=constraints,
                task_id=normalized_task_id,
                sandbox=sandbox,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            self._jobs[normalized_task_id] = future
            future.add_done_callback(lambda completed, tid=normalized_task_id: self._emit_final(tid, completed))
        return {
            "ok": True,
            "status": "queued",
            "agent": "Codex",
            "backend": "openai-codex-cli",
            "task_id": normalized_task_id,
        }

    def task_status(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = self._task_id(task_id)
        with self._jobs_lock:
            future = self._jobs.get(normalized_task_id)
        if future is None:
            return {"ok": False, "status": "not_found", "task_id": normalized_task_id}
        if future.cancelled():
            return {"ok": False, "status": "cancelled", "task_id": normalized_task_id}
        if not future.done():
            return {"ok": True, "status": "running" if future.running() else "queued", "task_id": normalized_task_id}
        result = self._future_result(future, normalized_task_id)
        return {"ok": bool(result.get("ok")), "status": str(result.get("status") or "completed"), "task_id": normalized_task_id}

    def task_result(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = self._task_id(task_id)
        with self._jobs_lock:
            future = self._jobs.get(normalized_task_id)
        if future is None:
            return {"ok": False, "status": "not_found", "task_id": normalized_task_id, "result_ready": False}
        if not future.done():
            return {
                "ok": True,
                "status": "running" if future.running() else "queued",
                "task_id": normalized_task_id,
                "result_ready": False,
            }
        return {**self._future_result(future, normalized_task_id), "result_ready": True}

    def run_task(
        self,
        *,
        project: str,
        working_path: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str] | None = None,
        task_id: str = "",
        sandbox: str = "workspace-write",
        model: str = "",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        project = project.strip()
        objective = objective.strip()
        sandbox = sandbox.strip().lower()
        if not project:
            raise ValueError("project must not be empty")
        if sandbox not in self._ALLOWED_SANDBOXES:
            raise ValueError(f"sandbox must be one of: {sorted(self._ALLOWED_SANDBOXES)}")
        criteria, normalized_constraints, timeout = self._validate_request(
            objective, acceptance_criteria, constraints or [], timeout_seconds
        )

        workdir = self.file_service.resolve_project_path(project, working_path.strip() or ".")
        if workdir.is_file():
            workdir = workdir.parent
        if not workdir.is_dir():
            raise FileNotFoundError(f"Working path not found: {working_path}")

        resolved = self._resolved_executable()
        if not resolved:
            return {
                "ok": False,
                "status": "cli_not_found",
                "agent": "Codex",
                "backend": "openai-codex-cli",
                "task_id": self._task_id(task_id or f"codex-{uuid.uuid4().hex[:12]}"),
                "error": f"Codex CLI executable not found: {self.executable}",
            }

        normalized_task_id = self._task_id(task_id or f"codex-{uuid.uuid4().hex[:12]}")
        prompt = self._build_prompt(objective, criteria, normalized_constraints, sandbox)
        args = [resolved, "exec", "--ephemeral", "--sandbox", sandbox]
        if model.strip():
            args.extend(["--model", model.strip()])
        args.append(prompt)

        self._emit(
            "task.started",
            task_id=normalized_task_id,
            agent_id="codex",
            data={
                "startedAt": self._now(),
                "backend": "openai-codex-cli",
                "workingPath": str(workdir),
                "sandbox": sandbox,
                "model": model.strip() or None,
            },
        )
        self._emit(
            "agent.busy",
            agent_id="codex",
            data={"name": "Codex", "type": "codex_agent", "backend": "openai-codex-cli", "currentTaskId": normalized_task_id},
        )

        with self._run_slots:
            run = self.process_service.run(args, cwd=workdir, timeout_seconds=timeout)
        stdout = str(run.get("stdout") or "").strip()
        stderr = str(run.get("stderr") or "").strip()
        return {
            "ok": bool(run.get("ok")),
            "status": "completed" if run.get("ok") else ("timed_out" if run.get("timed_out") else "codex_failed"),
            "agent": "Codex",
            "backend": "openai-codex-cli",
            "task_id": normalized_task_id,
            "working_path": str(workdir),
            "sandbox": sandbox,
            "model": model.strip() or None,
            "final_output": stdout,
            "stderr": stderr,
            "process": {
                "returncode": run.get("returncode"),
                "timed_out": run.get("timed_out"),
                "duration_seconds": run.get("duration_seconds"),
                "output_truncated": run.get("output_truncated"),
            },
        }

    def _validate_request(
        self,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str],
        timeout_seconds: int | None,
    ) -> tuple[list[str], list[str], int]:
        objective = objective.strip()
        if not objective:
            raise ValueError("objective must not be empty")
        if len(objective) > self._MAX_OBJECTIVE_CHARS:
            raise ValueError(f"objective exceeds {self._MAX_OBJECTIVE_CHARS} characters")
        if len(acceptance_criteria) > self._MAX_CRITERIA_ITEMS:
            raise ValueError(f"acceptance_criteria exceeds {self._MAX_CRITERIA_ITEMS} items")
        if len(constraints) > self._MAX_CONSTRAINT_ITEMS:
            raise ValueError(f"constraints exceeds {self._MAX_CONSTRAINT_ITEMS} items")
        criteria = [str(x).strip() for x in acceptance_criteria if str(x).strip()]
        normalized_constraints = [str(x).strip() for x in constraints if str(x).strip()]
        if not criteria:
            raise ValueError("acceptance_criteria must contain at least one item")
        for label, values in (("acceptance_criteria", criteria), ("constraints", normalized_constraints)):
            if any(len(item) > self._MAX_ITEM_CHARS for item in values):
                raise ValueError(f"{label} item exceeds {self._MAX_ITEM_CHARS} characters")
        timeout = self.timeout_seconds if timeout_seconds is None else int(timeout_seconds)
        timeout = max(30, timeout)
        if timeout > self._MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must not exceed {self._MAX_TIMEOUT_SECONDS}")
        return criteria, normalized_constraints, timeout

    @staticmethod
    def _build_prompt(objective: str, criteria: list[str], constraints: list[str], sandbox: str) -> str:
        criteria_text = "\n".join(f"- {item}" for item in criteria)
        constraints_text = "\n".join(f"- {str(item).strip()}" for item in constraints if str(item).strip()) or "- None beyond repository instructions and sandbox policy."
        write_note = (
            "You may edit files required to complete the task inside the current workspace."
            if sandbox == "workspace-write"
            else "Do not modify files; inspect and report only."
        )
        return (
            "You are a coding worker dispatched by A0-ProjectsMCP.\n"
            f"Objective:\n{objective}\n\n"
            f"Acceptance criteria:\n{criteria_text}\n\n"
            f"Constraints:\n{constraints_text}\n\n"
            f"Execution policy:\n- {write_note}\n"
            "- Follow all AGENTS.md/repository instructions that apply.\n"
            "- Keep changes narrowly scoped; do not commit, push, reset, or rewrite Git history.\n"
            "- Run relevant validation when practical.\n"
            "- In the final response summarize changed files, validation performed, and remaining risks."
        )

    def _emit_final(self, task_id: str, future: Future[dict[str, Any]]) -> None:
        result = self._future_result(future, task_id)
        self._emit(
            "task.completed" if result.get("ok") else "task.failed",
            task_id=task_id,
            agent_id="codex",
            severity="info" if result.get("ok") else "error",
            data={"completedAt": self._now(), "resultStatus": result.get("status")},
        )
        self._emit(
            "agent.idle",
            agent_id="codex",
            data={"name": "Codex", "type": "codex_agent", "backend": "openai-codex-cli", "currentTaskId": None},
        )

    @staticmethod
    def _future_result(future: Future[dict[str, Any]], task_id: str) -> dict[str, Any]:
        try:
            return future.result()
        except Exception as exc:
            return {
                "ok": False,
                "status": "internal_error",
                "agent": "Codex",
                "backend": "openai-codex-cli",
                "task_id": task_id,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _emit(
        self,
        event_type: str,
        *,
        severity: str = "info",
        task_id: str | None = None,
        agent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(
                event_type,
                source="codex_agent",
                severity=severity,
                task_id=task_id,
                agent_id=agent_id,
                data=data,
            )
        except Exception:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _task_id(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
        if not cleaned:
            raise ValueError("task_id is invalid")
        return cleaned[:120]
