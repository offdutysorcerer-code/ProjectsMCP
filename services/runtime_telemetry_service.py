from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_platform.telemetry_context import current_telemetry_context
from services.execution_runtime_health import ExecutionRuntimeHealthAggregator


_COLLECTIONS = ("tasks", "agents", "toolExecutions", "claims", "waits", "dispatches")
_DEFAULT_LIMITS = {
    "tasks": 500,
    "agents": 200,
    "toolExecutions": 500,
    "claims": 300,
    "waits": 300,
    "dispatches": 500,
}
_ACTIVE_STATUSES = {
    "tasks": {"created", "queued", "assigned", "running", "waiting"},
    "agents": {"busy"},
    "toolExecutions": {"running"},
    "claims": {"held"},
    "waits": {"waiting"},
    "dispatches": {"pending", "requested", "accepted", "initializing", "dispatching", "sending", "running"},
}


class RuntimeTelemetryService:
    """Thread-safe event store and derived runtime snapshot for A0 telemetry."""

    def __init__(
        self,
        root_dir: Path,
        max_recent_events: int = 500,
        collection_limits: dict[str, int] | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.events_dir = self.root_dir / "events"
        self.state_path = self.root_dir / "state.json"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.max_recent_events = max(50, int(max_recent_events))
        self.collection_limits = dict(_DEFAULT_LIMITS)
        for key, value in (collection_limits or {}).items():
            if key in self.collection_limits:
                self.collection_limits[key] = max(1, int(value))
        self.boot_id = f"boot-{uuid.uuid4().hex}"
        self._lock = threading.RLock()
        self._sequence = 0
        self._state: dict[str, dict[str, Any]] = {key: {} for key in _COLLECTIONS}
        self._recent_events: list[dict[str, Any]] = []
        self._load_previous_state()
        self._recover_previous_boot()
        self._enforce_retention()
        self._write_state()

    def emit(
        self,
        event_type: str,
        *,
        source: str,
        severity: str = "info",
        task_id: str | None = None,
        agent_id: str | None = None,
        request_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            correlation = self._resolve_correlation(
                task_id=task_id,
                run_id=run_id,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
            )
            self._sequence += 1
            event = {
                "eventId": f"evt-{uuid.uuid4().hex[:16]}",
                "sequence": self._sequence,
                "timestamp": self._now(),
                "type": event_type,
                "source": source,
                "severity": severity,
                "bootId": self.boot_id,
                **correlation,
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
            self._enforce_retention()
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
                "generatedAt": self._now(),
                "bootId": self.boot_id,
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
                "executionRuntimeHealth": ExecutionRuntimeHealthAggregator.aggregate(tools),
                "recentEvents": list(self._recent_events),
            }

    def recent_events(self, limit: int = 100) -> dict[str, Any]:
        with self._lock:
            items = self._recent_events[-max(1, min(int(limit), self.max_recent_events)) :]
            return {"count": len(items), "events": list(items)}

    def snapshot_without_events(self) -> dict[str, Any]:
        collections = {key: list(value.values()) for key, value in self._state.items()}
        return {
            "updatedAt": self._now(),
            "bootId": self.boot_id,
            **collections,
            "executionRuntimeHealth": ExecutionRuntimeHealthAggregator.aggregate(collections["toolExecutions"]),
        }

    def _resolve_correlation(
        self,
        *,
        task_id: str | None,
        run_id: str | None,
        trace_id: str | None,
        span_id: str | None,
        parent_span_id: str | None,
    ) -> dict[str, str | None]:
        context = current_telemetry_context()
        task = self._state["tasks"].get(task_id or "") if task_id else None
        return {
            "runId": run_id or (context.run_id if context else None) or (task or {}).get("runId"),
            "traceId": trace_id or (context.trace_id if context else None) or (task or {}).get("traceId"),
            "spanId": span_id or (context.span_id if context else None) or (task or {}).get("spanId"),
            "parentSpanId": parent_span_id or (context.parent_span_id if context else None) or (task or {}).get("parentSpanId"),
        }

    def _append_event(self, event: dict[str, Any]) -> None:
        day = event["timestamp"][:10]
        path = self.events_dir / f"{day}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _write_state(self) -> None:
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(self.snapshot_without_events(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.state_path)

    def _load_previous_state(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        if not isinstance(loaded, dict):
            return
        previous_boot_id = str(loaded.get("bootId") or "legacy-boot")
        for collection in _COLLECTIONS:
            items = loaded.get(collection)
            if not isinstance(items, list):
                continue
            id_field = {
                "tasks": "taskId",
                "agents": "agentId",
                "toolExecutions": "requestId",
                "claims": "claimId",
                "waits": "waitId",
                "dispatches": "dispatchId",
            }[collection]
            for raw in items:
                if not isinstance(raw, dict) or not raw.get(id_field):
                    continue
                item = dict(raw)
                item.setdefault("bootId", previous_boot_id)
                item.setdefault("runId", None)
                item.setdefault("traceId", None)
                item.setdefault("spanId", None)
                item.setdefault("parentSpanId", None)
                self._state[collection][str(item[id_field])] = item

    def _recover_previous_boot(self) -> None:
        recovered_at = self._now()
        for collection in ("tasks", "toolExecutions", "dispatches"):
            for item in self._state[collection].values():
                if str(item.get("status") or "").casefold() not in _ACTIVE_STATUSES[collection]:
                    continue
                item["status"] = "interrupted"
                item["interruptedAt"] = recovered_at
                item["interruptedByBootId"] = self.boot_id
                item["updatedAt"] = recovered_at
                if collection == "toolExecutions":
                    item["endedAt"] = recovered_at
        for collection in ("claims", "waits"):
            for item in self._state[collection].values():
                if str(item.get("status") or "").casefold() in _ACTIVE_STATUSES[collection]:
                    item["status"] = "stale"
                    item["staleAt"] = recovered_at
                    item["staleByBootId"] = self.boot_id
                    item["updatedAt"] = recovered_at
        for agent in self._state["agents"].values():
            if str(agent.get("status") or "").casefold() == "busy":
                agent["status"] = "idle"
                agent["currentTaskId"] = None
                agent["normalizedAt"] = recovered_at
                agent["normalizedByBootId"] = self.boot_id
                agent["lastActivityAt"] = recovered_at

    def _enforce_retention(self) -> None:
        for collection, items in self._state.items():
            limit = self.collection_limits[collection]
            if len(items) <= limit:
                continue
            active_statuses = _ACTIVE_STATUSES[collection]
            active = [
                (key, item)
                for key, item in items.items()
                if str(item.get("status") or "").casefold() in active_statuses
            ]
            terminal = [
                (key, item)
                for key, item in items.items()
                if str(item.get("status") or "").casefold() not in active_statuses
            ]
            terminal.sort(key=lambda pair: self._item_timestamp(pair[1]), reverse=True)
            keep = dict(active)
            available = max(0, limit - len(active))
            keep.update(terminal[:available])
            self._state[collection] = keep

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
            item["agentId"] = agent_id or item.get("agentId")
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
            self._apply_correlation(item, event)
            return

        if typ.startswith("agent.") and agent_id:
            item = self._state["agents"].setdefault(agent_id, {"agentId": agent_id})
            item.update(data)
            item["lastActivityAt"] = timestamp
            if typ == "agent.online": item["status"] = "idle"
            elif typ == "agent.offline": item["status"] = "offline"
            elif typ == "agent.busy": item["status"] = "busy"
            elif typ == "agent.idle": item["status"] = "idle"
            self._apply_correlation(item, event)
            return

        if typ.startswith("tool.") and request_id:
            item = self._state["toolExecutions"].setdefault(
                request_id,
                {"executionId": f"tool-{request_id}", "requestId": request_id},
            )
            item.update(data)
            item["taskId"] = task_id
            item["agentId"] = agent_id
            if typ == "tool.started":
                item["status"] = "running"
                item["startedAt"] = timestamp
            elif typ in {"tool.completed", "tool.failed", "tool.cancelled"}:
                item["status"] = typ.split(".", 1)[1]
                item["endedAt"] = timestamp
            self._apply_correlation(item, event)
            return

        if typ.startswith("resource."):
            claim_id = str(data.get("claimId") or "")
            if claim_id:
                item = self._state["claims"].setdefault(claim_id, {"claimId": claim_id})
                item.update(data)
                item["taskId"] = task_id or item.get("taskId")
                item["status"] = "held" if typ == "resource.claimed" else "released" if typ == "resource.released" else "conflict"
                item["updatedAt"] = timestamp
                self._apply_correlation(item, event)
            return

        if typ.startswith("dispatch."):
            dispatch_id = str(data.get("dispatchId") or event["eventId"])
            item = self._state["dispatches"].setdefault(dispatch_id, {"dispatchId": dispatch_id})
            item.update(data)
            item["taskId"] = task_id
            item["agentId"] = agent_id or item.get("agentId")
            item["updatedAt"] = timestamp
            item["status"] = typ.split(".", 1)[1]
            self._apply_correlation(item, event)
            return

        if typ.startswith("wait."):
            wait_id = str(data.get("waitId") or event["eventId"])
            item = self._state["waits"].setdefault(wait_id, {"waitId": wait_id})
            item.update(data)
            item["taskId"] = task_id
            item["agentId"] = agent_id
            item["updatedAt"] = timestamp
            item["status"] = "waiting" if typ == "wait.started" else "ended"
            self._apply_correlation(item, event)

    @staticmethod
    def _apply_correlation(item: dict[str, Any], event: dict[str, Any]) -> None:
        item["bootId"] = event.get("bootId")
        for field in ("runId", "traceId", "spanId", "parentSpanId"):
            item[field] = event.get(field)

    @staticmethod
    def _item_timestamp(item: dict[str, Any]) -> str:
        return str(
            item.get("updatedAt")
            or item.get("endedAt")
            or item.get("startedAt")
            or item.get("lastActivityAt")
            or ""
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
