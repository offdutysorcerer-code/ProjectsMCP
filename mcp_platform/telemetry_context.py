from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class TelemetryContext:
    """Correlation carried through one in-process execution context."""

    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None

    def as_event_fields(self) -> dict[str, str | None]:
        return {
            "runId": self.run_id,
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
        }


_CURRENT: ContextVar[TelemetryContext | None] = ContextVar(
    "a0_runtime_telemetry_context",
    default=None,
)


def current_telemetry_context() -> TelemetryContext | None:
    return _CURRENT.get()


def new_tool_context() -> TelemetryContext:
    """Create a root MCP span, or a child span when already inside one."""
    parent = current_telemetry_context()
    return TelemetryContext(
        run_id=parent.run_id if parent else f"run-{uuid.uuid4().hex}",
        trace_id=parent.trace_id if parent else f"trace-{uuid.uuid4().hex}",
        span_id=f"span-{uuid.uuid4().hex[:16]}",
        parent_span_id=parent.span_id if parent else None,
    )


@contextmanager
def use_telemetry_context(context: TelemetryContext) -> Iterator[TelemetryContext]:
    token: Token[TelemetryContext | None] = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
