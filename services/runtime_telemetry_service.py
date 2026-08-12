from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RuntimeTelemetryService:
    """Thread-safe event store and derived runtime snapshot for A0 orchestration telemetry."""

    def __init__(self, root_dir: Path, max_recent_events: int = 500) -> None:
        self.root_dir = root_dir.resolve()
        self.events_dir = self.root_dir / "events"
        self.state_path = self.root_dir / "state.json"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.max_recent_events = max(50, int(max_recent_events))
        self._lock = threading.RLock()
        self._sequence = 0
        self._state: dict[str, dict[str, Any]] = {
            "tasks": {},
            "agents": {},
            "toolExecutions": {},
            "claims": {},
            "waits": {},
            "dispatches": {},
        }
        self._recent_events: list[dict[str, Any]] = []

    def emit(
        self,
        event_type: str,
        *,
        source: str,
        severity: str = "info",
        task_id: str | None = None,
        agent_id: str | None = None,
        request_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            event = {
                "eventId": f"evt-{uuid.uuid4().hex[:16]}",
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "source": source,
                "severity": severity,
                "taskId": task_id,
                "agentId": agent_id,
                "requestId": request_id,
                "data": dict(data or {}),
            }
            self._append_event(event)
            self._apply_event(event)
            self._recent_events.append(event)
            if len(self._recent_events) > self.max_recent_events:
                self._recent_events = self._recent_events[-self.max_recent_events :]
            self._write_state()
            return event

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tasks = list(self._state["tasks"].values())
            agents = list(self._state["agents"].values())
            tools = list(self._state["toolExecutions"].values())
            claims = list(self._state["claims"].values())
            waits = list(self._state["waits"].values())
            dispatches = list(self._state["dispatches"].values())
            return {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "agentsOnline": sum(1 for x in agents if x.get("status") not in {"offline"}),
                    "agentsBusy": sum(1 for x in agents if x.get("status") == "busy"),
                    "tasksQueued": sum(1 for x in tasks if x.get("status") == "queued"),
                    "tasksRunning": sum(1 for x in tasks if x.get("status") == "running"),
                    "activeTools": sum(1 for x in tools if x.get("status") == "running"),
                    "activeClaims": sum(1 for x in claims if x.get("status") == "held"),
                    "waitingTasks": sum(1 for x in waits if x.get("status") == "waiting"),
                    "failures": sum(1 for x in tasks if x.get("status") == "failed")
                    + sum(1 for x in tools if x.get("status") == "failed"),
                },
                "agents": agents,
                "tasks": tasks,
                "toolExecutions": tools,
                "claims": claims,
                "waits": waits,
                "dispatches": dispatches,
                "recentEvents": list(self._recent_events),
            }

    def recent_events(self, limit: int = 100) -> dict[str, Any]:
        with self._lock:
            items = self._recent_events[-max(1, min(int(limit), self.max_recent_events)) :]
            return {"count": len(items), "events": list(items)}

    def _append_event(self, event: dict[str, Any]) -> None:
        day = event["timestamp"][:10]
        path = self.events_dir / f"{day}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _write_state(self) -> None:
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.snapshot_without_events(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.state_path)

    def snapshot_without_events(self) -> dict[str, Any]:
        return {
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            **{key: list(value.values()) for key, value in self._state.items()},
        }

    def _apply_event(self, event: dict[str, Any]) -> None:
        typ = event["type"]
        data = dict(event.get("data") or {})
        timestamp = event["timestamp"]
        task_id = event.get("taskId")
        agent_id = event.get("agentId")
        request_id = event.get("requestId")

        if typ.startswith("task.") and task_id:
            item = self._state["tasks"].setdefault(task_id, {"taskId": task_id})
            item.update(data)
            item["updatedAt"] = timestamp
            item["status"] = {
                "task.created": "created",
                "task.queued": "queued",
                "task.assigned": "assigned",
                "task.started": "running",
                "task.waiting": "waiting",
                "task.completed": "completed",
                "task.failed": "failed",
                "task.cancelled": "cancelled",
                "task.blocked": "blocked",
            }.get(typ, item.get("status", "unknown"))
            return

        if typ.startswith("agent.") and agent_id:
            item = self._state["agents"].setdefault(agent_id, {"agentId": agent_id})
            item.update(data)
            item["lastActivityAt"] = timestamp
            if typ == "agent.online": item["status"] = "idle"
            elif typ == "agent.offline": item["status"] = "offline"
            elif typ == "agent.busy": item["status"] = "busy"
            elif typ == "agent.idle": item["status"] = "idle"
            return

        if typ.startswith("tool.") and request_id:
            item = self._state["toolExecutions"].setdefault(request_id, {"executionId": f"tool-{request_id}", "requestId": request_id})
            item.update(data)
            item["taskId"] = task_id
            item["agentId"] = agent_id
            if typ == "tool.started":
                item["status"] = "running"
                item["startedAt"] = timestamp
            elif typ in {"tool.completed", "tool.failed", "tool.cancelled"}:
                item["status"] = typ.split(".", 1)[1]
                item["endedAt"] = timestamp
            return

        if typ.startswith("resource."):
            claim_id = str(data.get("claimId") or "")
            if claim_id:
                item = self._state["claims"].setdefault(claim_id, {"claimId": claim_id})
                item.update(data)
                item["status"] = "held" if typ == "resource.claimed" else "released" if typ == "resource.released" else "conflict"
                item["updatedAt"] = timestamp
            return

        if typ.startswith("dispatch."):
            dispatch_id = str(data.get("dispatchId") or event["eventId"])
            item = self._state["dispatches"].setdefault(dispatch_id, {"dispatchId": dispatch_id})
            item.update(data)
            item["taskId"] = task_id
            item["updatedAt"] = timestamp
            item["status"] = typ.split(".", 1)[1]
            return

        if typ.startswith("wait."):
            wait_id = str(data.get("waitId") or event["eventId"])
            item = self._state["waits"].setdefault(wait_id, {"waitId": wait_id})
            item.update(data)
            item["taskId"] = task_id
            item["agentId"] = agent_id
            item["updatedAt"] = timestamp
            item["status"] = "waiting" if typ == "wait.started" else "ended"
