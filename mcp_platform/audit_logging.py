from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger("projectsmcp.audit")

_SENSITIVE_KEYS = {
    "token",
    "authtoken",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credentials",
}

_LARGE_TEXT_KEYS = {
    "content",
    "script",
    "message",
    "objective",
    "instructions",
    "old_text",
    "new_text",
}

_PREVIEW_CHARS = 180
_MAX_STRING_CHARS = 500
_MAX_ITEMS = 30
_MAX_DEPTH = 5


def _escape_text(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _text_summary(value: str) -> dict[str, Any]:
    escaped = _escape_text(value)
    preview = escaped[:_PREVIEW_CHARS]
    if len(escaped) > _PREVIEW_CHARS:
        preview += f"...<+{len(escaped) - _PREVIEW_CHARS} chars>"
    return {
        "length": len(value),
        "preview": preview,
    }


def _sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    key_folded = key.casefold()
    if key_folded in _SENSITIVE_KEYS:
        return "***REDACTED***"
    if isinstance(value, str) and key_folded in _LARGE_TEXT_KEYS:
        return _text_summary(value)
    if depth >= _MAX_DEPTH:
        if isinstance(value, dict):
            return f"<dict:{len(value)} keys>"
        if isinstance(value, (list, tuple, set)):
            return f"<{type(value).__name__}:{len(value)} items>"
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = _escape_text(value)
        return text if len(text) <= _MAX_STRING_CHARS else text[:_MAX_STRING_CHARS] + f"...<+{len(text)-_MAX_STRING_CHARS} chars>"
    if isinstance(value, dict):
        items = list(value.items())
        sanitized = {
            str(k): _sanitize(v, key=str(k), depth=depth + 1)
            for k, v in items[:_MAX_ITEMS]
        }
        if len(items) > _MAX_ITEMS:
            sanitized["_truncated"] = f"+{len(items) - _MAX_ITEMS} keys"
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized = [_sanitize(v, depth=depth + 1) for v in items[:_MAX_ITEMS]]
        if len(items) > _MAX_ITEMS:
            sanitized.append(f"...<+{len(items)-_MAX_ITEMS} items>")
        return sanitized
    return _sanitize(str(value), depth=depth + 1)


def _summarize_call(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return {str(k): _sanitize(v, key=str(k)) for k, v in bound.arguments.items()}
    except Exception:
        return {
            "args": _sanitize(list(args)),
            "kwargs": _sanitize(kwargs),
        }


def _result_summary(result: Any) -> Any:
    if result is None:
        return None
    if hasattr(result, "model_dump"):
        try:
            result = result.model_dump()
        except Exception:
            pass
    return _sanitize(result)


def install_tool_audit(mcp: Any, telemetry: Any | None = None) -> None:
    """Wrap FastMCP's tool decorator so every registered tool is audit logged."""
    original_tool = mcp.tool

    def audited_tool(*decorator_args: Any, **decorator_kwargs: Any):
        original_decorator = original_tool(*decorator_args, **decorator_kwargs)

        def decorator(func: Callable[..., Any]):
            tool_name = decorator_kwargs.get("name") or getattr(func, "__name__", "unknown_tool")

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any):
                    request_id = uuid.uuid4().hex[:12]
                    started = time.perf_counter()
                    params = _summarize_call(func, args, kwargs)
                    if telemetry is not None:
                        telemetry.emit(
                            "tool.started",
                            source="mcp",
                            task_id=str(kwargs.get("task_id") or "") or None,
                            request_id=request_id,
                            data={"tool": tool_name, "parameters": params},
                        )
                    logger.info(
                        "TOOL_START request_id=%s tool=%s params=%s",
                        request_id,
                        tool_name,
                        json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                    )
                    try:
                        result = await func(*args, **kwargs)
                    except asyncio.CancelledError:
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        if telemetry is not None:
                            telemetry.emit(
                                "tool.cancelled",
                                source="mcp",
                                task_id=str(kwargs.get("task_id") or "") or None,
                                request_id=request_id,
                                data={"tool": tool_name, "durationMs": elapsed_ms},
                            )
                        logger.warning(
                            "TOOL_CANCEL request_id=%s tool=%s duration_ms=%s",
                            request_id,
                            tool_name,
                            elapsed_ms,
                        )
                        raise
                    except Exception as exc:
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        if telemetry is not None:
                            telemetry.emit(
                                "tool.failed",
                                source="mcp",
                                severity="error",
                                task_id=str(kwargs.get("task_id") or "") or None,
                                request_id=request_id,
                                data={"tool": tool_name, "durationMs": elapsed_ms, "error": f"{type(exc).__name__}: {exc}"},
                            )
                        logger.exception(
                            "TOOL_ERROR request_id=%s tool=%s duration_ms=%s",
                            request_id,
                            tool_name,
                            elapsed_ms,
                        )
                        raise
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    if telemetry is not None:
                        telemetry.emit(
                            "tool.completed",
                            source="mcp",
                            task_id=str(kwargs.get("task_id") or "") or None,
                            request_id=request_id,
                            data={"tool": tool_name, "durationMs": elapsed_ms, "resultSummary": _result_summary(result)},
                        )
                    logger.info(
                        "TOOL_END request_id=%s tool=%s duration_ms=%s result=%s",
                        request_id,
                        tool_name,
                        elapsed_ms,
                        json.dumps(_result_summary(result), ensure_ascii=False, separators=(",", ":")),
                    )
                    return result

                return original_decorator(async_wrapper)

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any):
                request_id = uuid.uuid4().hex[:12]
                started = time.perf_counter()
                params = _summarize_call(func, args, kwargs)
                if telemetry is not None:
                    telemetry.emit(
                        "tool.started",
                        source="mcp",
                        task_id=str(kwargs.get("task_id") or "") or None,
                        request_id=request_id,
                        data={"tool": tool_name, "parameters": params},
                    )
                logger.info(
                    "TOOL_START request_id=%s tool=%s params=%s",
                    request_id,
                    tool_name,
                    json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                )
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    if telemetry is not None:
                        telemetry.emit(
                            "tool.failed",
                            source="mcp",
                            severity="error",
                            task_id=str(kwargs.get("task_id") or "") or None,
                            request_id=request_id,
                            data={"tool": tool_name, "durationMs": elapsed_ms, "error": f"{type(exc).__name__}: {exc}"},
                        )
                    logger.exception(
                        "TOOL_ERROR request_id=%s tool=%s duration_ms=%s",
                        request_id,
                        tool_name,
                        elapsed_ms,
                    )
                    raise
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if telemetry is not None:
                    telemetry.emit(
                        "tool.completed",
                        source="mcp",
                        task_id=str(kwargs.get("task_id") or "") or None,
                        request_id=request_id,
                        data={"tool": tool_name, "durationMs": elapsed_ms, "resultSummary": _result_summary(result)},
                    )
                logger.info(
                    "TOOL_END request_id=%s tool=%s duration_ms=%s result=%s",
                    request_id,
                    tool_name,
                    elapsed_ms,
                    json.dumps(_result_summary(result), ensure_ascii=False, separators=(",", ":")),
                )
                return result

            return original_decorator(sync_wrapper)

        return decorator

    mcp.tool = audited_tool
