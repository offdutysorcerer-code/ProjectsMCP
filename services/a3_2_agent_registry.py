from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class A3_2AgentRegistry:
    """Persistent local mapping, task state, path claims, and dispatch state for logical A3_2 agents."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._lock:
            data = await self._load()
            return [self._public_agent(agent) for agent in data["agents"].values()]

    async def get_agent(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = data["agents"].get(key)
            if agent is None:
                raise KeyError(f"A3_2 agent not found: {name}")
            return self._public_agent(agent)

    async def register_agent(
        self,
        name: str,
        role: str,
        tab_id: str,
        instructions: str = "",
    ) -> dict[str, Any]:
        """Register an agent. ``instructions`` is retained as a compatibility alias for base instructions."""
        key = self._normalize_name(name)
        role = role.strip()
        tab_id = tab_id.strip()
        base_instructions = instructions.strip()
        if not role:
            raise ValueError("role must not be empty")
        if not tab_id:
            raise ValueError("tab_id must not be empty")

        now = self._now()
        async with self._lock:
            data = await self._load()
            previous = data["agents"].get(key)
            same_tab = bool(previous and previous.get("tabId") == tab_id)
            agent = {
                "name": name.strip(),
                "role": role,
                "tabId": tab_id,
                "baseInstructions": base_instructions,
                "initialized": bool(previous and same_tab and previous.get("initialized")),
                "createdAt": previous.get("createdAt") if previous else now,
                "updatedAt": now,
                "lastSentAt": previous.get("lastSentAt") if previous else None,
                "cooldownUntil": previous.get("cooldownUntil") if previous else None,
                "rateLimitCount": int(previous.get("rateLimitCount", 0)) if previous else 0,
                "currentTaskId": previous.get("currentTaskId") if previous else None,
            }
            data["agents"][key] = agent
            await self._save(data)
            return self._public_agent(agent)

    async def unregister_agent(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = data["agents"].pop(key, None)
            if agent is None:
                raise KeyError(f"A3_2 agent not found: {name}")
            for claim_key in [k for k, claim in data["claims"].items() if claim.get("agentKey") == key]:
                data["claims"].pop(claim_key, None)
            task_id = agent.get("currentTaskId")
            if task_id and task_id in data["tasks"]:
                data["tasks"][task_id]["status"] = "orphaned"
                data["tasks"][task_id]["updatedAt"] = self._now()
            await self._save(data)
            return self._public_agent(agent)

    async def mark_initialized(self, name: str, initialized: bool = True) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            agent["initialized"] = bool(initialized)
            agent["updatedAt"] = self._now()
            await self._save(data)
            return self._public_agent(agent)

    async def assign_task(
        self,
        name: str,
        task_id: str,
        objective: str,
        project: str,
        working_path: str = "",
        read_scopes: list[str] | None = None,
        write_scopes: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        key = self._normalize_name(name)
        task_id = task_id.strip()
        objective = objective.strip()
        project = project.strip()
        if not task_id:
            raise ValueError("task_id must not be empty")
        if not objective:
            raise ValueError("objective must not be empty")
        if not project:
            raise ValueError("project must not be empty")

        now = self._now()
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            previous_task_id = agent.get("currentTaskId")
            if previous_task_id and previous_task_id != task_id:
                previous = data["tasks"].get(previous_task_id)
                if previous and previous.get("status") == "assigned":
                    raise ValueError(
                        f"A3_2 agent '{agent['name']}' already has active task: {previous_task_id}"
                    )
            existing = data["tasks"].get(task_id)
            if existing and existing.get("agentKey") != key and existing.get("status") == "assigned":
                raise ValueError(f"Task already assigned to another agent: {task_id}")

            task = {
                "taskId": task_id,
                "agent": agent["name"],
                "agentKey": key,
                "objective": objective,
                "project": project,
                "workingPath": working_path.strip(),
                "readScopes": self._clean_strings(read_scopes),
                "writeScopes": self._clean_strings(write_scopes),
                "acceptanceCriteria": self._clean_strings(acceptance_criteria),
                "status": "assigned",
                "createdAt": existing.get("createdAt") if existing else now,
                "updatedAt": now,
            }
            data["tasks"][task_id] = task
            agent["currentTaskId"] = task_id
            agent["updatedAt"] = now
            await self._save(data)
            return self._public_task(task)

    async def complete_task(self, name: str, task_id: str, status: str = "completed") -> dict[str, Any]:
        key = self._normalize_name(name)
        task_id = task_id.strip()
        status = status.strip().casefold()
        if status not in {"completed", "cancelled", "blocked"}:
            raise ValueError("status must be completed, cancelled, or blocked")
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            task = data["tasks"].get(task_id)
            if task is None:
                raise KeyError(f"Task not found: {task_id}")
            if task.get("agentKey") != key:
                raise ValueError(f"Task {task_id} is not assigned to agent '{agent['name']}'")
            task["status"] = status
            task["updatedAt"] = self._now()
            if agent.get("currentTaskId") == task_id:
                agent["currentTaskId"] = None
                agent["updatedAt"] = self._now()
            for claim_key in [
                k
                for k, claim in data["claims"].items()
                if claim.get("agentKey") == key and claim.get("taskId") == task_id
            ]:
                data["claims"].pop(claim_key, None)
            await self._save(data)
            return self._public_task(task)

    async def list_tasks(self, status: str = "") -> list[dict[str, Any]]:
        wanted = status.strip().casefold()
        async with self._lock:
            data = await self._load()
            tasks = list(data["tasks"].values())
            if wanted:
                tasks = [task for task in tasks if str(task.get("status", "")).casefold() == wanted]
            return [self._public_task(task) for task in tasks]

    async def claim_paths(self, name: str, paths: list[str], task_id: str = "") -> list[dict[str, Any]]:
        key = self._normalize_name(name)
        cleaned = self._clean_paths(paths)
        if not cleaned:
            raise ValueError("paths must contain at least one path")
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            effective_task_id = task_id.strip() or str(agent.get("currentTaskId") or "")
            task: dict[str, Any] | None = None
            if effective_task_id:
                task = data["tasks"].get(effective_task_id)
                if task is None or task.get("agentKey") != key:
                    raise ValueError(f"Task is not assigned to agent '{agent['name']}': {effective_task_id}")

            project = str(task.get("project") if task else "")
            working_path = str(task.get("workingPath") if task else "")
            conflicts: list[dict[str, Any]] = []
            for requested in cleaned:
                for claim in data["claims"].values():
                    if claim.get("agentKey") == key:
                        continue
                    if str(claim.get("project", "")) != project:
                        continue
                    if str(claim.get("workingPath", "")) != working_path:
                        continue
                    if self._paths_overlap(requested, str(claim.get("path", ""))):
                        conflicts.append(self._public_claim(claim))
            if conflicts:
                details = ", ".join(f"{c['path']} by {c['agent']}" for c in conflicts)
                raise ValueError(f"Path claim conflict: {details}")

            now = self._now()
            results: list[dict[str, Any]] = []
            for requested in cleaned:
                claim_key = self._claim_key(key, requested)
                claim = {
                    "path": requested,
                    "agent": agent["name"],
                    "agentKey": key,
                    "taskId": effective_task_id or None,
                    "project": project,
                    "workingPath": working_path,
                    "claimedAt": now,
                }
                data["claims"][claim_key] = claim
                results.append(self._public_claim(claim))
            await self._save(data)
            return results

    async def release_paths(self, name: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
        key = self._normalize_name(name)
        requested = set(self._clean_paths(paths)) if paths else None
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            released: list[dict[str, Any]] = []
            for claim_key, claim in list(data["claims"].items()):
                if claim.get("agentKey") != key:
                    continue
                if requested is not None and str(claim.get("path")) not in requested:
                    continue
                released.append(self._public_claim(claim))
                data["claims"].pop(claim_key, None)
            await self._save(data)
            return released

    async def list_claims(self) -> list[dict[str, Any]]:
        async with self._lock:
            data = await self._load()
            return [self._public_claim(claim) for claim in data["claims"].values()]

    async def check_dispatch(self, name: str, min_interval_seconds: int = 20) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            now = datetime.now(timezone.utc)
            waits: list[tuple[str, int]] = []

            self._append_wait(waits, "global_rate_limit", data["globalDispatch"].get("cooldownUntil"), now)
            self._append_wait(waits, "agent_rate_limit", agent.get("cooldownUntil"), now)
            self._append_interval_wait(
                waits,
                "global_min_interval",
                data["globalDispatch"].get("lastSentAt"),
                now,
                min_interval_seconds,
            )
            self._append_interval_wait(
                waits,
                "agent_min_interval",
                agent.get("lastSentAt"),
                now,
                min_interval_seconds,
            )

            if waits:
                reason, retry_after = max(waits, key=lambda item: item[1])
                return {
                    "allowed": False,
                    "reason": reason,
                    "retryAfterSeconds": retry_after,
                    "agent": self._public_agent(agent),
                    "globalCooldownUntil": data["globalDispatch"].get("cooldownUntil"),
                }

            return {
                "allowed": True,
                "reason": None,
                "retryAfterSeconds": 0,
                "agent": self._public_agent(agent),
                "globalCooldownUntil": data["globalDispatch"].get("cooldownUntil"),
            }

    async def mark_send_started(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            now = self._now()
            agent["lastSentAt"] = now
            agent["updatedAt"] = now
            data["globalDispatch"]["lastSentAt"] = now
            await self._save(data)
            return self._public_agent(agent)

    async def record_rate_limit(self, name: str, retry_after_seconds: int = 300) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            global_state = data["globalDispatch"]

            agent_count = int(agent.get("rateLimitCount", 0)) + 1
            global_count = int(global_state.get("rateLimitCount", 0)) + 1
            count = max(agent_count, global_count)
            exponential = min(300 * (2 ** max(0, count - 1)), 1800)
            backoff = max(int(retry_after_seconds), exponential)
            until = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            until_text = until.isoformat()

            agent["rateLimitCount"] = agent_count
            agent["cooldownUntil"] = until_text
            agent["updatedAt"] = self._now()
            global_state["rateLimitCount"] = global_count
            global_state["cooldownUntil"] = until_text
            await self._save(data)

            return {
                "agent": self._public_agent(agent),
                "retryAfterSeconds": backoff,
                "cooldownUntil": until_text,
                "globalRateLimitCount": global_count,
            }

    async def record_success(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            agent["rateLimitCount"] = 0
            agent["cooldownUntil"] = None
            agent["updatedAt"] = self._now()
            data["globalDispatch"]["rateLimitCount"] = 0
            data["globalDispatch"]["cooldownUntil"] = None
            await self._save(data)
            return self._public_agent(agent)

    async def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_data()
        text = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
            raise ValueError(f"Invalid A3_2 agent registry: {self.path}")
        data.setdefault("version", 3)
        data.setdefault("tasks", {})
        data.setdefault("claims", {})
        data.setdefault(
            "globalDispatch",
            {"lastSentAt": None, "cooldownUntil": None, "rateLimitCount": 0},
        )
        for agent in data["agents"].values():
            if "baseInstructions" not in agent:
                agent["baseInstructions"] = str(agent.pop("instructions", "") or "")
            agent.setdefault("lastSentAt", None)
            agent.setdefault("cooldownUntil", None)
            agent.setdefault("rateLimitCount", 0)
            agent.setdefault("currentTaskId", None)
        return data

    async def _save(self, data: dict[str, Any]) -> None:
        data["version"] = 3
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        await asyncio.to_thread(temp.write_text, text, encoding="utf-8")
        await asyncio.to_thread(temp.replace, self.path)

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "version": 3,
            "globalDispatch": {
                "lastSentAt": None,
                "cooldownUntil": None,
                "rateLimitCount": 0,
            },
            "agents": {},
            "tasks": {},
            "claims": {},
        }

    @staticmethod
    def _required_agent(data: dict[str, Any], key: str, original_name: str) -> dict[str, Any]:
        agent = data["agents"].get(key)
        if agent is None:
            raise KeyError(f"A3_2 agent not found: {original_name}")
        return agent

    @staticmethod
    def _public_agent(agent: dict[str, Any]) -> dict[str, Any]:
        result = dict(agent)
        base = str(result.get("baseInstructions", "") or "")
        result["baseInstructions"] = base
        result["instructions"] = base
        result.pop("agentKey", None)
        return result

    @staticmethod
    def _public_task(task: dict[str, Any]) -> dict[str, Any]:
        result = dict(task)
        result.pop("agentKey", None)
        return result

    @staticmethod
    def _public_claim(claim: dict[str, Any]) -> dict[str, Any]:
        result = dict(claim)
        result.pop("agentKey", None)
        return result

    @staticmethod
    def _clean_strings(values: list[str] | None) -> list[str]:
        return [str(value).strip() for value in (values or []) if str(value).strip()]

    @classmethod
    def _clean_paths(cls, paths: list[str] | None) -> list[str]:
        result: list[str] = []
        for raw in paths or []:
            value = cls._normalize_path(str(raw))
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _normalize_path(path: str) -> str:
        value = path.strip().replace("\\", "/")
        while "//" in value:
            value = value.replace("//", "/")
        return value.strip("/")

    @classmethod
    def _paths_overlap(cls, left: str, right: str) -> bool:
        a = cls._normalize_path(left).casefold()
        b = cls._normalize_path(right).casefold()
        if not a or not b:
            return False
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    @staticmethod
    def _claim_key(agent_key: str, path: str) -> str:
        return f"{agent_key}:{path.casefold()}"

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _append_wait(
        cls,
        waits: list[tuple[str, int]],
        reason: str,
        until_value: Any,
        now: datetime,
    ) -> None:
        until = cls._parse_datetime(until_value)
        if until is None or until <= now:
            return
        seconds = max(1, int((until - now).total_seconds() + 0.999))
        waits.append((reason, seconds))

    @classmethod
    def _append_interval_wait(
        cls,
        waits: list[tuple[str, int]],
        reason: str,
        last_value: Any,
        now: datetime,
        interval_seconds: int,
    ) -> None:
        last = cls._parse_datetime(last_value)
        if last is None:
            return
        until = last + timedelta(seconds=max(0, int(interval_seconds)))
        if until <= now:
            return
        seconds = max(1, int((until - now).total_seconds() + 0.999))
        waits.append((reason, seconds))

    @staticmethod
    def _normalize_name(name: str) -> str:
        value = name.strip().casefold()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
