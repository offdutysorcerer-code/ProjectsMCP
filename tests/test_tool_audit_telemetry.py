from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mcp_platform.audit_logging import install_tool_audit
from services.runtime_telemetry_service import RuntimeTelemetryService


class FakeMCP:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def tool(self, *args, **kwargs):
        def decorator(func):
            self.registered[str(kwargs.get("name") or func.__name__)] = func
            return func

        return decorator


class ToolAuditTelemetryTests(unittest.TestCase):
    def make_runtime(self, root: Path) -> RuntimeTelemetryService:
        return RuntimeTelemetryService(root, max_recent_events=100)

    def test_sync_tool_and_child_task_share_correlation(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = self.make_runtime(Path(tmp))
            mcp = FakeMCP()
            install_tool_audit(mcp, runtime)

            @mcp.tool()
            def demo_tool(task_id: str = "task-sync") -> dict[str, bool]:
                runtime.emit(
                    "task.queued",
                    source="test",
                    task_id=task_id,
                    data={"objective": "child work"},
                )
                return {"ok": True}

            result = demo_tool(task_id="task-sync")
            self.assertEqual({"ok": True}, result)
            events = runtime.recent_events(10)["events"]
            started = next(item for item in events if item["type"] == "tool.started")
            completed = next(item for item in events if item["type"] == "tool.completed")
            task = next(item for item in events if item["type"] == "task.queued")

            self.assertTrue(started["bootId"].startswith("boot-"))
            self.assertTrue(started["runId"].startswith("run-"))
            self.assertTrue(started["traceId"].startswith("trace-"))
            self.assertTrue(started["spanId"].startswith("span-"))
            self.assertIsNone(started["parentSpanId"])
            for item in (completed, task):
                self.assertEqual(started["runId"], item["runId"])
                self.assertEqual(started["traceId"], item["traceId"])
                self.assertEqual(started["spanId"], item["spanId"])

    def test_async_tool_lifecycle_keeps_one_span(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = self.make_runtime(Path(tmp))
            mcp = FakeMCP()
            install_tool_audit(mcp, runtime)

            @mcp.tool()
            async def async_demo() -> str:
                await asyncio.sleep(0)
                return "done"

            self.assertEqual("done", asyncio.run(async_demo()))
            events = runtime.recent_events(10)["events"]
            started = next(item for item in events if item["type"] == "tool.started")
            completed = next(item for item in events if item["type"] == "tool.completed")
            self.assertEqual(started["runId"], completed["runId"])
            self.assertEqual(started["traceId"], completed["traceId"])
            self.assertEqual(started["spanId"], completed["spanId"])

    def test_nested_audited_tool_creates_child_span(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = self.make_runtime(Path(tmp))
            mcp = FakeMCP()
            install_tool_audit(mcp, runtime)

            @mcp.tool()
            def inner_tool() -> str:
                return "inner"

            @mcp.tool()
            def outer_tool() -> str:
                return inner_tool()

            self.assertEqual("inner", outer_tool())
            starts = [item for item in runtime.recent_events(10)["events"] if item["type"] == "tool.started"]
            self.assertEqual(2, len(starts))
            outer, inner = starts
            self.assertEqual(outer["runId"], inner["runId"])
            self.assertEqual(outer["traceId"], inner["traceId"])
            self.assertNotEqual(outer["spanId"], inner["spanId"])
            self.assertEqual(outer["spanId"], inner["parentSpanId"])


if __name__ == "__main__":
    unittest.main()
