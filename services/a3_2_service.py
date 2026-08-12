from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from services.a3_2_agent_registry import A3_2AgentRegistry


class A3_2RateLimitError(RuntimeError):
    """Raised when A3_2 reports a ChatGPT rate-limit modal as HTTP 429."""

    def __init__(self, message: str, retry_after_seconds: int = 300) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.status = "rate_limited"


class A3_2Service:
    """HTTP client for the local A3_2 WebView2 browser runtime."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5139",
        timeout_seconds: float = 120,
        artifacts_dir: Path | None = None,
        telemetry: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.artifacts_dir = artifacts_dir
        self.telemetry = telemetry
        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self.agent_registry = A3_2AgentRegistry(self.artifacts_dir / "agents.json", telemetry=telemetry)
        else:
            self.agent_registry = None

    async def status(self) -> dict[str, Any]:
        try:
            data = await self._request_json("GET", "/api/status", timeout_seconds=10)
            return {"ok": True, "base_url": self.base_url, **data}
        except Exception as exc:
            return {"ok": False, "base_url": self.base_url, "error": str(exc)}

    async def list_tabs(self) -> Any:
        return await self._request_json("GET", "/api/tabs")

    async def new_tab(self, url: str = "", activate: bool = True) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            "/api/tabs",
            {"url": url or None, "activate": activate},
        )

    async def close_tab(self, tab_id: str) -> dict[str, Any]:
        await self._request_bytes("DELETE", f"/api/tabs/{tab_id}")
        return {"ok": True, "tabId": tab_id, "status": "closed"}

    async def activate_tab(self, tab_id: str) -> dict[str, Any]:
        await self._request_bytes("POST", f"/api/tabs/{tab_id}/activate")
        return {"ok": True, "tabId": tab_id, "status": "activated"}

    async def navigate(self, tab_id: str, input_value: str) -> dict[str, Any]:
        await self._request_bytes(
            "POST",
            f"/api/tabs/{tab_id}/navigate",
            {"input": input_value},
        )
        return {"ok": True, "tabId": tab_id, "status": "navigated", "input": input_value}

    async def get_text(self, tab_id: str, max_chars: int = 12000) -> dict[str, Any]:
        max_chars = max(1, min(int(max_chars), 200000))
        raw, content_type = await self._request_bytes(
            "GET",
            f"/api/tabs/{tab_id}/text?maxChars={max_chars}",
        )
        text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "tabId": tab_id,
            "text": text,
            "contentType": content_type,
            "truncated": len(text) >= max_chars,
        }

    async def execute_javascript(self, tab_id: str, script: str) -> dict[str, Any]:
        if not script.strip():
            raise ValueError("script must not be empty")
        data = await self._request_json(
            "POST",
            f"/api/tabs/{tab_id}/javascript",
            {"script": script},
        )
        return {
            "ok": True,
            "tabId": tab_id,
            "result": str(data.get("result", "")),
        }

    async def screenshot(self, tab_id: str) -> dict[str, Any]:
        if self.artifacts_dir is None:
            raise RuntimeError("A3_2 screenshot artifacts directory is not configured.")

        raw, _ = await self._request_bytes("GET", f"/api/tabs/{tab_id}/screenshot")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = self.artifacts_dir / f"a3_2_{tab_id}_{timestamp}.png"
        await asyncio.to_thread(path.write_bytes, raw)
        return {
            "ok": True,
            "tabId": tab_id,
            "path": str(path),
            "bytes": len(raw),
        }

    async def chatgpt_send_message(
        self,
        tab_id: str,
        message: str,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message must not be empty")

        timeout_seconds = max(5, min(int(timeout_seconds), 600))
        return await self._request_json(
            "POST",
            f"/api/chatgpt/{tab_id}/send",
            {"message": message, "timeoutSeconds": timeout_seconds},
            timeout_seconds=timeout_seconds + 10,
        )

    async def chatgpt_get_messages(self, tab_id: str) -> Any:
        return await self._request_json("GET", f"/api/chatgpt/{tab_id}/messages")

    async def chatgpt_get_last_response(self, tab_id: str) -> dict[str, Any]:
        return await self._request_json("GET", f"/api/chatgpt/{tab_id}/last-assistant")

    async def register_agent(
        self,
        name: str,
        role: str,
        tab_id: str,
        instructions: str = "",
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        tabs = await self.list_tabs()
        if not any(str(tab.get("tabId")) == tab_id for tab in tabs):
            raise ValueError(f"A3_2 tab not found: {tab_id}")
        agent = await registry.register_agent(name, role, tab_id, instructions)
        self._emit(
            "agent.online",
            agent_id=name.strip().casefold(),
            data={"name": agent.get("name"), "type": "chatgpt_agent", "backend": "a3_2", "tabId": tab_id},
        )
        return agent

    async def list_agents(self) -> dict[str, Any]:
        registry = self._require_agent_registry()
        agents = await registry.list_agents()
        tabs = await self.list_tabs()
        tab_ids = {str(tab.get("tabId")) for tab in tabs}
        enriched = [
            {**agent, "tabAvailable": str(agent.get("tabId")) in tab_ids}
            for agent in agents
        ]
        return {"count": len(enriched), "agents": enriched}

    async def unregister_agent(self, name: str) -> dict[str, Any]:
        registry = self._require_agent_registry()
        agent = await registry.unregister_agent(name)
        self._emit(
            "agent.offline",
            agent_id=name.strip().casefold(),
            data={"name": agent.get("name"), "type": "chatgpt_agent", "backend": "a3_2"},
        )
        return {"ok": True, "agent": agent}

    async def initialize_agent(
        self,
        name: str,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        agent = await registry.get_agent(name)
        dispatch = await registry.check_dispatch(name)
        if not dispatch["allowed"]:
            return self._cooldown_result(dispatch, agent, "Agent initialization is waiting for cooldown.")

        prompt = self._build_agent_initialization_prompt(agent)
        await registry.mark_send_started(name)
        try:
            result = await self.chatgpt_send_message(
                str(agent["tabId"]),
                prompt,
                timeout_seconds,
            )
        except A3_2RateLimitError as exc:
            limited = await registry.record_rate_limit(name, exc.retry_after_seconds)
            return self._rate_limited_result(
                limited,
                error=str(exc),
                agent=limited["agent"],
            )

        await registry.record_success(name)
        assistant_text = str(result.get("assistantMessage", {}).get("text") or "").strip()
        ready = assistant_text.rstrip(".!").strip().casefold() == "agent_ready"
        updated = await registry.mark_initialized(name, ready)
        return {
            "ok": ready,
            "status": "ok" if ready else "initialization_failed",
            "agent": updated,
            "initializationResult": result,
            "retryAfterSeconds": 0,
            "cooldownUntil": None,
            "error": None if ready else f"Expected AGENT_READY but received: {assistant_text}",
        }

    async def send_to_agent(
        self,
        name: str,
        message: str,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        agent = await registry.get_agent(name)
        if not agent.get("initialized"):
            raise RuntimeError(
                f"A3_2 agent '{agent['name']}' has not been initialized. "
                "Call a3_2_initialize_agent first."
            )

        dispatch = await registry.check_dispatch(name)
        if not dispatch["allowed"]:
            return self._cooldown_result(dispatch, agent, "Agent dispatch is waiting for cooldown.")

        await registry.mark_send_started(name)
        try:
            result = await self.chatgpt_send_message(
                str(agent["tabId"]),
                message,
                timeout_seconds,
            )
        except A3_2RateLimitError as exc:
            limited = await registry.record_rate_limit(name, exc.retry_after_seconds)
            return self._rate_limited_result(
                limited,
                error=str(exc),
                agent=limited["agent"],
            )

        updated = await registry.record_success(name)
        return {
            "ok": True,
            "status": "ok",
            "agent": updated,
            "result": result,
            "retryAfterSeconds": 0,
            "cooldownUntil": None,
            "error": None,
        }

    async def assign_agent_task(
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
        registry = self._require_agent_registry()
        task = await registry.assign_task(
            name,
            task_id,
            objective,
            project,
            working_path,
            read_scopes,
            write_scopes,
            acceptance_criteria,
        )
        agent_id = name.strip().casefold()
        self._emit(
            "task.assigned",
            task_id=task_id,
            agent_id=agent_id,
            data={**task, "assignedTo": agent_id, "backend": "a3_2"},
        )
        self._emit(
            "dispatch.accepted",
            task_id=task_id,
            agent_id=agent_id,
            data={"dispatchId": f"dispatch-{task_id}", "fromAgentId": "mcp-client", "toAgentId": agent_id, "backend": "a3_2"},
        )
        return task

    async def complete_agent_task(
        self,
        name: str,
        task_id: str,
        status: str = "completed",
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        task = await registry.complete_task(name, task_id, status)
        event_type = {
            "completed": "task.completed",
            "cancelled": "task.cancelled",
            "blocked": "task.blocked",
        }.get(status.strip().casefold(), "task.completed")
        self._emit(
            event_type,
            task_id=task_id,
            agent_id=name.strip().casefold(),
            data={**task, "backend": "a3_2"},
        )
        return task

    async def list_agent_tasks(self, status: str = "") -> dict[str, Any]:
        registry = self._require_agent_registry()
        tasks = await registry.list_tasks(status)
        return {"count": len(tasks), "tasks": tasks}

    async def claim_agent_paths(
        self,
        name: str,
        paths: list[str],
        task_id: str = "",
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        claims = await registry.claim_paths(name, paths, task_id)
        for claim in claims:
            claim_id = self._claim_id(name, str(claim.get("taskId") or task_id or ""), str(claim.get("path") or ""))
            self._emit(
                "resource.claimed",
                task_id=str(claim.get("taskId") or task_id or "") or None,
                agent_id=name.strip().casefold(),
                data={"claimId": claim_id, "resourceType": "path", "resource": claim.get("path"), "mode": "exclusive", **claim},
            )
        return {"count": len(claims), "claims": claims}

    async def release_agent_paths(
        self,
        name: str,
        paths: list[str] | None = None,
    ) -> dict[str, Any]:
        registry = self._require_agent_registry()
        claims = await registry.release_paths(name, paths)
        for claim in claims:
            self._emit(
                "resource.released",
                task_id=str(claim.get("taskId") or "") or None,
                agent_id=name.strip().casefold(),
                data={
                    "claimId": self._claim_id(name, str(claim.get("taskId") or ""), str(claim.get("path") or "")),
                    "resourceType": "path",
                    "resource": claim.get("path"),
                    "mode": "exclusive",
                    **claim,
                },
            )
        return {"count": len(claims), "claims": claims}

    async def list_agent_path_claims(self) -> dict[str, Any]:
        registry = self._require_agent_registry()
        claims = await registry.list_claims()
        return {"count": len(claims), "claims": claims}

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
                source="a3_2",
                severity=severity,
                task_id=task_id,
                agent_id=agent_id,
                data=data,
            )
        except Exception:
            pass

    @staticmethod
    def _claim_id(name: str, task_id: str, path: str) -> str:
        normalized = path.strip().replace("\\", "/").casefold()
        return f"a3_2:{name.strip().casefold()}:{task_id.strip()}:{normalized}"

    def _require_agent_registry(self) -> A3_2AgentRegistry:
        if self.agent_registry is None:
            raise RuntimeError("A3_2 agent registry is not configured.")
        return self.agent_registry

    @staticmethod
    def _cooldown_result(
        dispatch: dict[str, Any],
        agent: dict[str, Any],
        error: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "cooldown",
            "agent": agent,
            "result": None,
            "initializationResult": None,
            "retryAfterSeconds": int(dispatch.get("retryAfterSeconds", 0)),
            "cooldownUntil": dispatch.get("globalCooldownUntil") or agent.get("cooldownUntil"),
            "error": error,
        }

    @staticmethod
    def _rate_limited_result(
        limited: dict[str, Any],
        error: str,
        agent: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "rate_limited",
            "agent": agent,
            "result": None,
            "initializationResult": None,
            "retryAfterSeconds": int(limited.get("retryAfterSeconds", 300)),
            "cooldownUntil": limited.get("cooldownUntil"),
            "error": error,
        }

    @staticmethod
    def _build_agent_initialization_prompt(agent: dict[str, Any]) -> str:
        base_instructions = " ".join(str(agent.get("baseInstructions") or agent.get("instructions") or "").split())
        parts = [
            f"You are {agent['name']}, role: {agent['role']}.",
            "Follow only tasks from the coordinating agent, stay within the scope defined by each task, and do not recursively invoke other agents.",
        ]
        if base_instructions:
            parts.append(base_instructions)
        parts.append("Reply exactly AGENT_READY.")
        return " ".join(parts)

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        raw, _ = await self._request_bytes(method, path, payload, timeout_seconds)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    async def _request_bytes(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bytes, str]:
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Accept": "application/json, text/plain, image/png"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        timeout = float(timeout_seconds or self.timeout_seconds)

        def execute() -> tuple[bytes, str]:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read(), response.headers.get_content_type()
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429:
                    retry_after = 300
                    header_value = exc.headers.get("Retry-After") if exc.headers else None
                    if header_value:
                        try:
                            retry_after = max(1, int(header_value))
                        except ValueError:
                            pass
                    message = error_body or str(exc.reason)
                    try:
                        payload_data = json.loads(error_body) if error_body else {}
                        retry_after = max(
                            retry_after,
                            int(payload_data.get("retryAfterSeconds", retry_after)),
                        )
                        message = str(payload_data.get("error") or message)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass
                    raise A3_2RateLimitError(message, retry_after) from exc

                raise RuntimeError(
                    f"A3_2 HTTP {exc.code} for {method} {path}: {error_body or exc.reason}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"A3_2 is not reachable at {self.base_url}: {exc.reason}"
                ) from exc

        return await asyncio.to_thread(execute)
