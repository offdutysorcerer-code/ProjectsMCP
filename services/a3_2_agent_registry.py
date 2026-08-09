from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class A3_2AgentRegistry:
    """Persistent local mapping and dispatch state for logical A3_2 agents."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._lock:
            data = await self._load()
            return [dict(agent) for agent in data["agents"].values()]

    async def get_agent(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = data["agents"].get(key)
            if agent is None:
                raise KeyError(f"A3_2 agent not found: {name}")
            return dict(agent)

    async def register_agent(
        self,
        name: str,
        role: str,
        tab_id: str,
        instructions: str = "",
    ) -> dict[str, Any]:
        key = self._normalize_name(name)
        role = role.strip()
        tab_id = tab_id.strip()
        instructions = instructions.strip()
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
                "instructions": instructions,
                "initialized": bool(previous and same_tab and previous.get("initialized")),
                "createdAt": previous.get("createdAt") if previous else now,
                "updatedAt": now,
                "lastSentAt": previous.get("lastSentAt") if previous else None,
                "cooldownUntil": previous.get("cooldownUntil") if previous else None,
                "rateLimitCount": int(previous.get("rateLimitCount", 0)) if previous else 0,
            }
            data["agents"][key] = agent
            await self._save(data)
            return dict(agent)

    async def unregister_agent(self, name: str) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = data["agents"].pop(key, None)
            if agent is None:
                raise KeyError(f"A3_2 agent not found: {name}")
            await self._save(data)
            return dict(agent)

    async def mark_initialized(self, name: str, initialized: bool = True) -> dict[str, Any]:
        key = self._normalize_name(name)
        async with self._lock:
            data = await self._load()
            agent = self._required_agent(data, key, name)
            agent["initialized"] = bool(initialized)
            agent["updatedAt"] = self._now()
            await self._save(data)
            return dict(agent)

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
                    "agent": dict(agent),
                    "globalCooldownUntil": data["globalDispatch"].get("cooldownUntil"),
                }

            return {
                "allowed": True,
                "reason": None,
                "retryAfterSeconds": 0,
                "agent": dict(agent),
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
            return dict(agent)

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
                "agent": dict(agent),
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
            return dict(agent)

    async def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_data()
        text = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
            raise ValueError(f"Invalid A3_2 agent registry: {self.path}")
        data.setdefault("version", 2)
        data.setdefault(
            "globalDispatch",
            {"lastSentAt": None, "cooldownUntil": None, "rateLimitCount": 0},
        )
        for agent in data["agents"].values():
            agent.setdefault("lastSentAt", None)
            agent.setdefault("cooldownUntil", None)
            agent.setdefault("rateLimitCount", 0)
        return data

    async def _save(self, data: dict[str, Any]) -> None:
        data["version"] = 2
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        await asyncio.to_thread(temp.write_text, text, encoding="utf-8")
        await asyncio.to_thread(temp.replace, self.path)

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "version": 2,
            "globalDispatch": {
                "lastSentAt": None,
                "cooldownUntil": None,
                "rateLimitCount": 0,
            },
            "agents": {},
        }

    @staticmethod
    def _required_agent(data: dict[str, Any], key: str, original_name: str) -> dict[str, Any]:
        agent = data["agents"].get(key)
        if agent is None:
            raise KeyError(f"A3_2 agent not found: {original_name}")
        return agent

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
