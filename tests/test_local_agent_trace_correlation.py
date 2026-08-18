from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mcp_platform.telemetry_context import new_tool_context, use_telemetry_context
from services.local_agent_service import LocalAgentService
from services.runtime_telemetry_service import RuntimeTelemetryService


class _DummyFileService:
    pass


class _DummyProcessService:
    pass


class _Future:
    def add_done_callback(self, callback) -> None:
        self.callback = callback

    def done(self) -> bool:
        return False


class _InspectingExecutor:
    def __init__(self, telemetry: RuntimeTelemetryService, expected_trace: str) -> None:
        self.telemetry = telemetry
        self.expected_trace = expected_trace
        self.checked = False

    def submit(self, *args, **kwargs):
        task = next(
            item
            for item in self.telemetry.snapshot()["tasks"]
            if item["taskId"] == "local-trace"
        )
        if task.get("traceId") != self.expected_trace:
            raise AssertionError("task correlation was not stored before worker submit")
        self.checked = True
        return _Future()


class LocalAgentTraceCorrelationTests(unittest.TestCase):
    def test_submit_records_task_correlation_before_worker_thread_starts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            telemetry = RuntimeTelemetryService(root / "runtime")
            service = LocalAgentService(
                _DummyFileService(),
                _DummyProcessService(),
                root / "worker",
                telemetry=telemetry,
            )
            service._executor.shutdown(wait=False, cancel_futures=True)
            context = new_tool_context()
            executor = _InspectingExecutor(telemetry, context.trace_id)
            service._executor = executor  # type: ignore[assignment]

            with use_telemetry_context(context):
                result = service.submit_task(
                    project="ai",
                    source_path="demo.py",
                    objective="trace ordering",
                    acceptance_criteria=["queued before worker submit"],
                    task_id="local-trace",
                )

            self.assertTrue(executor.checked)
            self.assertEqual("queued", result["status"])
            task = next(
                item
                for item in telemetry.snapshot()["tasks"]
                if item["taskId"] == "local-trace"
            )
            dispatch = next(
                item
                for item in telemetry.snapshot()["dispatches"]
                if item["taskId"] == "local-trace"
            )
            self.assertEqual(context.trace_id, task["traceId"])
            self.assertEqual(context.trace_id, dispatch["traceId"])


if __name__ == "__main__":
    unittest.main()
