from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.codex_agent_service import CodexAgentService


class FakeFileService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_project_path(self, project: str, working_path: str) -> Path:
        if project != "ai":
            raise ValueError("unknown project")
        return (self.root / working_path).resolve()


class FakeProcessService:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def run(self, command, *, cwd=None, timeout_seconds=None, env=None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return {
                "ok": True,
                "returncode": 0,
                "stdout": "ok",
                "stderr": "",
                "timed_out": False,
                "duration_seconds": self.delay,
                "output_truncated": False,
            }
        finally:
            with self.lock:
                self.active -= 1


class FakeTelemetry:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.lock = threading.Lock()

    def emit(self, event_type, **kwargs):
        with self.lock:
            self.events.append(event_type)


class CodexAgentServiceTests(unittest.TestCase):
    def make_service(self, root: Path, *, delay: float = 0.0, max_jobs: int = 2, telemetry=None):
        return CodexAgentService(
            file_service=FakeFileService(root),
            process_service=FakeProcessService(delay=delay),
            executable="codex",
            timeout_seconds=900,
            max_concurrent_jobs=max_jobs,
            telemetry=telemetry,
        )

    def test_rejects_oversized_timeout(self):
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                service.run_task(
                    project="ai",
                    working_path=".",
                    objective="audit",
                    acceptance_criteria=["done"],
                    timeout_seconds=3601,
                    sandbox="read-only",
                )

    def test_rejects_oversized_objective(self):
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            with self.assertRaisesRegex(ValueError, "objective exceeds"):
                service.run_task(
                    project="ai",
                    working_path=".",
                    objective="x" * 12001,
                    acceptance_criteria=["done"],
                    sandbox="read-only",
                )

    def test_direct_runs_respect_concurrency_limit(self):
        with TemporaryDirectory() as tmp, patch("services.codex_agent_service.shutil.which", return_value="codex.exe"):
            service = self.make_service(Path(tmp), delay=0.15, max_jobs=1)
            errors: list[Exception] = []

            def worker(task_id: str) -> None:
                try:
                    service.run_task(
                        project="ai",
                        working_path=".",
                        objective="audit",
                        acceptance_criteria=["done"],
                        task_id=task_id,
                        sandbox="read-only",
                    )
                except Exception as exc:  # pragma: no cover - diagnostic capture
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual([], errors)
            self.assertEqual(1, service.process_service.max_active)

    def test_submit_emits_queued_before_started(self):
        with TemporaryDirectory() as tmp, patch("services.codex_agent_service.shutil.which", return_value="codex.exe"):
            telemetry = FakeTelemetry()
            service = self.make_service(Path(tmp), delay=0.05, max_jobs=1, telemetry=telemetry)
            response = service.submit_task(
                project="ai",
                working_path=".",
                objective="audit",
                acceptance_criteria=["done"],
                task_id="ordering-test",
                sandbox="read-only",
            )
            self.assertEqual("queued", response["status"])
            deadline = time.time() + 2
            while time.time() < deadline and service.task_status("ordering-test")["status"] in {"queued", "running"}:
                time.sleep(0.01)
            self.assertIn("task.queued", telemetry.events)
            self.assertIn("task.started", telemetry.events)
            self.assertLess(telemetry.events.index("task.queued"), telemetry.events.index("task.started"))


if __name__ == "__main__":
    unittest.main()
