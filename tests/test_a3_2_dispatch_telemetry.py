from __future__ import annotations

import asyncio
from typing import Any

from services.a3_2_service import A3_2Service


class RecordingTelemetry:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event_type: str, **kwargs: Any) -> None:
        self.events.append({"type": event_type, **kwargs})


class DispatchRegistry:
    def __init__(self) -> None:
        self.states: list[tuple[str, str, str | None]] = []

    async def get_agent(self, name: str) -> dict[str, Any]:
        return {"name": name, "tabId": "tab-1", "initialized": True}

    async def check_dispatch(self, name: str) -> dict[str, Any]:
        return {"allowed": True}

    async def mark_send_started(self, name: str) -> None:
        return None

    async def record_success(self, name: str) -> dict[str, Any]:
        return await self.get_agent(name)

    async def update_task_dispatch_state(
        self, task_id: str, state: str, error: str | None = None
    ) -> None:
        self.states.append((task_id, state, error))


def test_auto_dispatch_emits_exact_prompt_and_lifecycle() -> None:
    telemetry = RecordingTelemetry()
    registry = DispatchRegistry()
    service = A3_2Service(telemetry=telemetry)
    service.agent_registry = registry  # type: ignore[assignment]

    async def fake_send(tab_id: str, message: str, timeout_seconds: int) -> dict[str, Any]:
        return {"assistantMessage": {"text": "accepted"}}

    service.chatgpt_send_message = fake_send  # type: ignore[method-assign]
    task = {
        "taskId": "task-42",
        "agent": "Worker One",
        "objective": "Refactor the execution view",
        "project": "A0-ProjectsMCP",
        "workingPath": "A0.ControlCenter",
        "readScopes": ["A0.ControlCenter"],
        "writeScopes": ["A0.ControlCenter/webroot"],
        "acceptanceCriteria": ["Direct MCP calls remain visible"],
    }

    asyncio.run(service._auto_dispatch_assigned_task(task))

    events = {event["type"]: event for event in telemetry.events}
    sending = events["dispatch.sending"]
    completed = events["dispatch.completed"]
    expected_prompt = service._build_task_dispatch_prompt(task)

    assert sending["data"]["dispatchPrompt"] == expected_prompt
    assert sending["data"]["objective"] == task["objective"]
    assert sending["data"]["workingPath"] == task["workingPath"]
    assert sending["data"]["readScopes"] == task["readScopes"]
    assert sending["data"]["writeScopes"] == task["writeScopes"]
    assert sending["data"]["acceptanceCriteria"] == task["acceptanceCriteria"]
    assert completed["data"]["dispatchPrompt"] == expected_prompt
    assert registry.states == [
        ("task-42", "dispatching", None),
        ("task-42", "dispatched", None),
    ]


def test_auto_dispatch_emits_failure_after_send_error() -> None:
    telemetry = RecordingTelemetry()
    registry = DispatchRegistry()
    service = A3_2Service(telemetry=telemetry)
    service.agent_registry = registry  # type: ignore[assignment]

    async def failed_send(tab_id: str, message: str, timeout_seconds: int) -> dict[str, Any]:
        raise RuntimeError("A3_2 unavailable")

    service.chatgpt_send_message = failed_send  # type: ignore[method-assign]
    task = {
        "taskId": "task-failed",
        "agent": "Worker One",
        "objective": "Attempt dispatch",
        "project": "A0-ProjectsMCP",
    }

    asyncio.run(service._auto_dispatch_assigned_task(task))

    event_types = [event["type"] for event in telemetry.events]
    assert "dispatch.sending" in event_types
    assert "dispatch.failed" in event_types
    assert registry.states[-1] == (
        "task-failed",
        "dispatch_failed",
        "A3_2 unavailable",
    )
