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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.artifacts_dir = artifacts_dir
        if self.artifacts_dir is not None:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            self.agent_registry = A3_2AgentRegistry(self.artifacts_dir / "agents.json")
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
        return await registry.register_agent(name, role, tab_id, instructions)

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
        instructions = " ".join(str(agent.get("instructions") or "").split())
        parts = [
            f"You are {agent['name']}, role: {agent['role']}.",
            "Follow only tasks from the coordinating agent, stay within scope, and do not recursively invoke other agents.",
        ]
        if instructions:
            parts.append(instructions)
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
