from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp_platform.telemetry_context import TelemetryContext, new_tool_context, use_telemetry_context
from services.runtime_telemetry_service import RuntimeTelemetryService


class RuntimeTelemetryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_emit_inherits_context_and_explicit_fields_take_precedence(self) -> None:
        service = RuntimeTelemetryService(self.root)
        context = TelemetryContext(
            run_id="run-context",
            trace_id="trace-context",
            span_id="span-context",
            parent_span_id="span-parent",
        )

        with use_telemetry_context(context):
            inherited = service.emit("task.queued", source="test", task_id="task-1")
            overridden = service.emit(
                "dispatch.sending",
                source="test",
                task_id="task-1",
                run_id="run-explicit",
                trace_id="trace-explicit",
                span_id="span-explicit",
                parent_span_id="parent-explicit",
                data={"dispatchId": "dispatch-1"},
            )

        self.assertEqual("run-context", inherited["runId"])
        self.assertEqual("trace-context", inherited["traceId"])
        self.assertEqual("span-context", inherited["spanId"])
        self.assertEqual("span-parent", inherited["parentSpanId"])
        self.assertEqual("run-explicit", overridden["runId"])
        self.assertEqual("trace-explicit", overridden["traceId"])
        self.assertEqual("span-explicit", overridden["spanId"])
        self.assertEqual("parent-explicit", overridden["parentSpanId"])

    def test_known_task_supplies_correlation_without_active_context(self) -> None:
        service = RuntimeTelemetryService(self.root)
        context = new_tool_context()
        with use_telemetry_context(context):
            service.emit("task.queued", source="mcp", task_id="task-fallback")

        event = service.emit(
            "dispatch.accepted",
            source="worker-thread",
            task_id="task-fallback",
            data={"dispatchId": "dispatch-fallback"},
        )

        self.assertEqual(context.run_id, event["runId"])
        self.assertEqual(context.trace_id, event["traceId"])
        self.assertEqual(context.span_id, event["spanId"])
        dispatch = service.snapshot()["dispatches"][0]
        self.assertEqual(context.trace_id, dispatch["traceId"])

    def test_restart_recovers_active_records_and_persists_new_boot(self) -> None:
        previous = RuntimeTelemetryService(self.root)
        with use_telemetry_context(new_tool_context()):
            previous.emit("task.started", source="test", task_id="task-active")
            previous.emit(
                "tool.started",
                source="mcp",
                task_id="task-active",
                request_id="request-active",
                data={"tool": "example_tool"},
            )
            previous.emit(
                "dispatch.sending",
                source="test",
                task_id="task-active",
                data={"dispatchId": "dispatch-active"},
            )
            previous.emit(
                "resource.claimed",
                source="test",
                task_id="task-active",
                data={"claimId": "claim-active", "resource": "README.md"},
            )
            previous.emit(
                "wait.started",
                source="test",
                task_id="task-active",
                data={"waitId": "wait-active"},
            )
            previous.emit(
                "agent.busy",
                source="test",
                agent_id="agent-active",
                data={"currentTaskId": "task-active"},
            )
        previous_boot_id = previous.boot_id

        recovered = RuntimeTelemetryService(self.root)
        snapshot = recovered.snapshot()

        self.assertNotEqual(previous_boot_id, recovered.boot_id)
        self.assertEqual("interrupted", snapshot["tasks"][0]["status"])
        self.assertEqual("interrupted", snapshot["toolExecutions"][0]["status"])
        self.assertEqual("interrupted", snapshot["dispatches"][0]["status"])
        self.assertEqual("stale", snapshot["claims"][0]["status"])
        self.assertEqual("stale", snapshot["waits"][0]["status"])
        self.assertEqual("idle", snapshot["agents"][0]["status"])
        self.assertIsNone(snapshot["agents"][0]["currentTaskId"])
        persisted = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(recovered.boot_id, persisted["bootId"])

    def test_retention_preserves_active_and_newest_terminal_records(self) -> None:
        service = RuntimeTelemetryService(
            self.root,
            collection_limits={"tasks": 3},
        )
        for index in range(5):
            task_id = f"completed-{index}"
            service.emit("task.created", source="test", task_id=task_id)
            service.emit("task.completed", source="test", task_id=task_id)
        service.emit("task.started", source="test", task_id="active")

        tasks = {item["taskId"]: item for item in service.snapshot()["tasks"]}

        self.assertEqual({"active", "completed-3", "completed-4"}, set(tasks))
        self.assertEqual("running", tasks["active"]["status"])


if __name__ == "__main__":
    unittest.main()
