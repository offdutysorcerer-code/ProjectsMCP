from __future__ import annotations

import ctypes
import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.executable_registry import ExecutableRegistry
from services.file_service import FileService
from services.process_service import ProcessService


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class LocalAgentService:
    """Dispatch narrowly-scoped coding tasks to the A28 LM Studio worker."""

    def __init__(
        self,
        file_service: FileService,
        process_service: ProcessService,
        worker_dir: Path,
        timeout_seconds: int = 180,
        max_concurrent_jobs: int = 4,
        telemetry: Any | None = None,
        executables: ExecutableRegistry | None = None,
    ) -> None:
        self.file_service = file_service
        self.process_service = process_service
        self.executables = executables or ExecutableRegistry(("git", "pwsh", "powershell"))
        self.worker_dir = worker_dir.resolve()
        self.worker_script = self.worker_dir / "local-coding-worker.ps1"
        self.token_file = self.worker_dir / "token.txt"
        self.tasks_dir = self.worker_dir / "tasks"
        self.results_dir = self.tasks_dir / "results"
        self.worktrees_dir = self.worker_dir / "worktrees"
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.max_concurrent_jobs = max(1, int(max_concurrent_jobs))
        self.telemetry = telemetry
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_jobs,
            thread_name_prefix="local-agent",
        )
        self._jobs: dict[str, Future[dict[str, Any]]] = {}
        self._jobs_lock = threading.Lock()
        self._source_locks_guard = threading.Lock()
        self._source_locks: dict[str, threading.Lock] = {}
        self._source_claims: dict[str, dict[str, str]] = {}
        self._scheduler_condition = threading.Condition()
        self._scheduler_active_cost = 0
        self._scheduler_active: dict[str, dict[str, Any]] = {}
        self.scheduler_parallel_limit = min(3, self.max_concurrent_jobs)

    def status(self) -> dict[str, Any]:
        with self._jobs_lock:
            active_jobs = sum(1 for future in self._jobs.values() if not future.done())
        with self._source_locks_guard:
            source_claims = list(self._source_claims.values())
        memory = self._memory_snapshot()
        with self._scheduler_condition:
            scheduler_active = list(self._scheduler_active.values())
            scheduler_active_cost = self._scheduler_active_cost
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
            "active_source_claims": len(source_claims),
            "source_claims": source_claims,
            "scheduler": {
                "capacity": self._scheduler_capacity(memory),
                "parallel_limit": self.scheduler_parallel_limit,
                "active_cost": scheduler_active_cost,
                "active": scheduler_active,
                "memory": memory,
            },
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

            # Record correlation before the worker thread starts. ContextVars do not
            # propagate into ThreadPoolExecutor workers, so task.started/final events
            # can reuse the correlation already stored on this task.
            self._emit(
                "task.queued",
                task_id=normalized_task_id,
                agent_id="localdeveloper",
                data={
                    "title": objective[:120],
                    "objective": objective,
                    "project": project,
                    "workingPath": source_path,
                    "assignedTo": "localdeveloper",
                    "backend": "lmstudio",
                    "queuedAt": self._now(),
                },
            )
            self._emit(
                "dispatch.accepted",
                task_id=normalized_task_id,
                agent_id="localdeveloper",
                data={
                    "dispatchId": f"dispatch-{normalized_task_id}",
                    "fromAgentId": "mcp-client",
                    "toAgentId": "localdeveloper",
                    "backend": "lmstudio",
                },
            )
            try:
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
            except Exception as exc:
                self._emit(
                    "task.failed",
                    task_id=normalized_task_id,
                    agent_id="localdeveloper",
                    severity="error",
                    data={"resultStatus": "submit_failed", "error": f"{type(exc).__name__}: {exc}"},
                )
                raise
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

        original_source_file = self.file_service.resolve_project_path(project, source_path)
        if not original_source_file.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        if not self.worker_script.is_file():
            raise FileNotFoundError(f"Local coding worker not found: {self.worker_script}")
        if not self.token_file.is_file():
            raise FileNotFoundError(f"LM Studio token file not found: {self.token_file}")

        normalized_task_id = self._task_id(task_id or f"local-{uuid.uuid4().hex[:12]}")
        source_bytes = original_source_file.stat().st_size
        task_class, task_cost = self._classify_task(source_bytes)
        scheduler_wait_seconds = self._acquire_scheduler_slot(
            normalized_task_id,
            task_class=task_class,
            task_cost=task_cost,
            source_bytes=source_bytes,
        )
        try:
            return self._run_task_isolated(
                project=project,
                source_path=source_path,
                objective=objective,
                criteria=criteria,
                constraints=constraints,
                normalized_task_id=normalized_task_id,
                max_changed_lines=max_changed_lines,
                validation_command=validation_command,
                timeout_seconds=timeout_seconds,
                original_source_file=original_source_file,
                task_class=task_class,
                task_cost=task_cost,
                scheduler_wait_seconds=scheduler_wait_seconds,
            )
        finally:
            self._release_scheduler_slot(normalized_task_id)

    def _run_task_isolated(
        self,
        *,
        project: str,
        source_path: str,
        objective: str,
        criteria: list[str],
        constraints: list[str] | None,
        normalized_task_id: str,
        max_changed_lines: int,
        validation_command: str,
        timeout_seconds: int | None,
        original_source_file: Path,
        task_class: str,
        task_cost: int,
        scheduler_wait_seconds: float,
    ) -> dict[str, Any]:
        claim_key = str(original_source_file.resolve()).casefold()
        source_lock = self._get_source_lock(claim_key)

        with source_lock:
            self._set_source_claim(claim_key, normalized_task_id, original_source_file)
            worktree_dir: Path | None = None
            repo_root: Path | None = None
            try:
                repo_root = self._git_repo_root(original_source_file)
                self._require_clean_repo(repo_root)
                worktree_dir = self._create_worktree(repo_root, normalized_task_id)
                relative_source = original_source_file.resolve().relative_to(repo_root.resolve())
                source_file = (worktree_dir / relative_source).resolve()
                if not source_file.is_file():
                    raise FileNotFoundError(f"Isolated source file not found: {relative_source}")

                self._emit(
                    "task.started",
                    task_id=normalized_task_id,
                    agent_id="localdeveloper",
                    data={
                        "startedAt": self._now(),
                        "backend": "lmstudio",
                        "worktreeDir": str(worktree_dir),
                        "sourceClaim": str(original_source_file),
                        "schedulerClass": task_class,
                        "schedulerCost": task_cost,
                        "schedulerWaitSeconds": scheduler_wait_seconds,
                    },
                )
                self._emit(
                    "agent.busy",
                    agent_id="localdeveloper",
                    data={"name": "LocalDeveloper", "type": "local_agent", "backend": "lmstudio", "currentTaskId": normalized_task_id},
                )
                task_file = self.tasks_dir / f"{normalized_task_id}.json"
                payload = {
                    "task_id": normalized_task_id,
                    "source_file": str(source_file),
                    "original_source_file": str(original_source_file),
                    "worktree_dir": str(worktree_dir),
                    "repo_root": str(repo_root),
                    "objective": objective,
                    "acceptance_criteria": criteria,
                    "constraints": [str(x).strip() for x in (constraints or []) if str(x).strip()],
                    "max_changed_lines": max(1, int(max_changed_lines)),
                    "validation_command": validation_command.strip(),
                    "scheduler_class": task_class,
                    "scheduler_cost": task_cost,
                    "scheduler_wait_seconds": scheduler_wait_seconds,
                }
                task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")

                timeout = self.timeout_seconds if timeout_seconds is None else max(10, int(timeout_seconds))
                powershell = self.executables.preferred_powershell(prefer_pwsh=False)
                if not powershell:
                    raise RuntimeError("PowerShell was not found when A0 started.")
                run = self.process_service.run(
                    [
                        powershell,
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
                        "worktree_dir": str(worktree_dir),
                        "scheduler_class": task_class,
                        "scheduler_cost": task_cost,
                        "scheduler_wait_seconds": scheduler_wait_seconds,
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
                        "worktree_dir": str(worktree_dir),
                        "scheduler_class": task_class,
                        "scheduler_cost": task_cost,
                        "scheduler_wait_seconds": scheduler_wait_seconds,
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
                    "worktree_dir": str(worktree_dir),
                    "repo_root": str(repo_root),
                    "original_source_file": str(original_source_file),
                    "scheduler_class": task_class,
                    "scheduler_cost": task_cost,
                    "scheduler_wait_seconds": scheduler_wait_seconds,
                    "result": result,
                    "diff": diff_text,
                }
            finally:
                if worktree_dir is not None and repo_root is not None:
                    self._remove_worktree(repo_root, worktree_dir)
                self._clear_source_claim(claim_key, normalized_task_id)

    @staticmethod
    def _classify_task(source_bytes: int) -> tuple[str, int]:
        if source_bytes <= 8 * 1024:
            return "small", 1
        if source_bytes <= 24 * 1024:
            return "medium", 2
        return "large", 4

    def _acquire_scheduler_slot(
        self,
        task_id: str,
        *,
        task_class: str,
        task_cost: int,
        source_bytes: int,
    ) -> float:
        started = time.monotonic()
        with self._scheduler_condition:
            while True:
                memory = self._memory_snapshot()
                capacity = self._scheduler_capacity(memory)
                effective_cost = min(task_cost, self.max_concurrent_jobs)
                if (
                    len(self._scheduler_active) < self.scheduler_parallel_limit
                    and self._scheduler_active_cost + effective_cost <= capacity
                ):
                    self._scheduler_active_cost += effective_cost
                    self._scheduler_active[task_id] = {
                        "task_id": task_id,
                        "class": task_class,
                        "cost": effective_cost,
                        "source_bytes": source_bytes,
                        "admitted_at": self._now(),
                    }
                    return round(time.monotonic() - started, 3)
                self._scheduler_condition.wait(timeout=1.0)

    def _release_scheduler_slot(self, task_id: str) -> None:
        with self._scheduler_condition:
            active = self._scheduler_active.pop(task_id, None)
            if active is not None:
                self._scheduler_active_cost = max(0, self._scheduler_active_cost - int(active.get("cost") or 0))
            self._scheduler_condition.notify_all()

    def _scheduler_capacity(self, memory: dict[str, Any] | None = None) -> int:
        hard_max = self.max_concurrent_jobs
        memory = memory or self._memory_snapshot()
        headroom_gb = memory.get("headroom_gb")
        if not isinstance(headroom_gb, (int, float)):
            return hard_max
        if headroom_gb < 8:
            return 1
        if headroom_gb < 16:
            return min(hard_max, 2)
        if headroom_gb < 32:
            return min(hard_max, 3)
        return hard_max

    @staticmethod
    def _memory_snapshot() -> dict[str, Any]:
        if hasattr(ctypes, "windll"):
            try:
                status = _MemoryStatusEx()
                status.dwLength = ctypes.sizeof(_MemoryStatusEx)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    gib = float(1024**3)
                    available_phys_gb = status.ullAvailPhys / gib
                    available_commit_gb = status.ullAvailPageFile / gib
                    return {
                        "available_physical_gb": round(available_phys_gb, 2),
                        "available_commit_gb": round(available_commit_gb, 2),
                        "memory_load_percent": int(status.dwMemoryLoad),
                        "headroom_gb": round(min(available_phys_gb, available_commit_gb), 2),
                    }
            except Exception:
                pass
        return {
            "available_physical_gb": None,
            "available_commit_gb": None,
            "memory_load_percent": None,
            "headroom_gb": None,
        }

    def _get_source_lock(self, claim_key: str) -> threading.Lock:
        with self._source_locks_guard:
            return self._source_locks.setdefault(claim_key, threading.Lock())

    def _set_source_claim(self, claim_key: str, task_id: str, source_file: Path) -> None:
        with self._source_locks_guard:
            self._source_claims[claim_key] = {
                "task_id": task_id,
                "source_file": str(source_file),
            }

    def _clear_source_claim(self, claim_key: str, task_id: str) -> None:
        with self._source_locks_guard:
            claim = self._source_claims.get(claim_key)
            if claim is not None and claim.get("task_id") == task_id:
                self._source_claims.pop(claim_key, None)

    def _git_repo_root(self, source_file: Path) -> Path:
        run = self.process_service.run(
            [self.executables.require("git"), "-C", str(source_file.parent), "rev-parse", "--show-toplevel"],
            cwd=source_file.parent,
            timeout_seconds=15,
        )
        if not run.get("ok"):
            raise RuntimeError(f"Source file is not inside a usable Git repository: {source_file}")
        value = str(run.get("stdout") or "").strip()
        if not value:
            raise RuntimeError(f"Git repository root could not be resolved for: {source_file}")
        return Path(value).resolve()

    def _require_clean_repo(self, repo_root: Path) -> None:
        run = self.process_service.run(
            [self.executables.require("git"), "-C", str(repo_root), "status", "--porcelain"],
            cwd=repo_root,
            timeout_seconds=15,
        )
        if not run.get("ok"):
            raise RuntimeError(f"Unable to inspect Git status: {repo_root}")
        dirty = str(run.get("stdout") or "").strip()
        if dirty:
            raise RuntimeError(
                "LocalDeveloper isolated worktree requires a clean source repository. "
                f"Commit/stash current changes first: {repo_root}"
            )

    def _create_worktree(self, repo_root: Path, task_id: str) -> Path:
        worktree_dir = (self.worktrees_dir / task_id).resolve()
        if worktree_dir.exists():
            self._remove_worktree(repo_root, worktree_dir)
            if worktree_dir.exists():
                shutil.rmtree(worktree_dir, ignore_errors=True)
        run = self.process_service.run(
            [self.executables.require("git"), "-C", str(repo_root), "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
            cwd=repo_root,
            timeout_seconds=60,
        )
        if not run.get("ok"):
            raise RuntimeError(f"Unable to create isolated Git worktree for {task_id}: {run.get('stderr') or run.get('stdout')}")
        return worktree_dir

    def _remove_worktree(self, repo_root: Path, worktree_dir: Path) -> None:
        try:
            self.process_service.run(
                [self.executables.require("git"), "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_dir)],
                cwd=repo_root,
                timeout_seconds=30,
            )
        except Exception:
            pass
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir, ignore_errors=True)
        try:
            self.process_service.run(
                [self.executables.require("git"), "-C", str(repo_root), "worktree", "prune"],
                cwd=repo_root,
                timeout_seconds=15,
            )
        except Exception:
            pass

    def _persist_future_result(self, task_id: str, future: Future[dict[str, Any]]) -> None:
        result = self._future_result(future, task_id)
        final_event = "task.completed" if result.get("ok") else "task.failed"
        self._emit(
            final_event,
            task_id=task_id,
            agent_id="localdeveloper",
            severity="info" if result.get("ok") else "error",
            data={"completedAt": self._now(), "resultStatus": result.get("status")},
        )
        self._emit(
            "agent.idle",
            agent_id="localdeveloper",
            data={"name": "LocalDeveloper", "type": "local_agent", "backend": "lmstudio", "currentTaskId": None},
        )
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
                source="local_agent",
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
