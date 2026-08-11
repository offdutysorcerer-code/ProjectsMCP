from __future__ import annotations

import asyncio
from typing import Any

from mcp_platform.context import PlatformContext


class LocalAgentPlugin:
    name = "local_agent"
    description = "Dispatch scoped coding tasks to the local LM Studio/Qwen worker and return validated candidate diffs."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.local_agent_service

        @mcp.tool()
        def local_agent_status() -> dict[str, Any]:
            """Check whether the A28 local coding worker and LM Studio token are available."""
            return service.status()

        @mcp.tool()
        def local_agent_submit_task(
            project: str,
            source_path: str,
            objective: str,
            acceptance_criteria: list[str],
            constraints: list[str] | None = None,
            task_id: str = "",
            max_changed_lines: int = 80,
            validation_command: str = "",
            timeout_seconds: int = 180,
        ) -> dict[str, Any]:
            """Queue one local coding task and return immediately with a task ID."""
            return service.submit_task(
                project=project,
                source_path=source_path,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                constraints=constraints,
                task_id=task_id,
                max_changed_lines=max_changed_lines,
                validation_command=validation_command,
                timeout_seconds=timeout_seconds,
            )

        @mcp.tool()
        def local_agent_task_status(task_id: str) -> dict[str, Any]:
            """Return queued/running/completed status for a submitted local agent task."""
            return service.task_status(task_id)

        @mcp.tool()
        def local_agent_task_result(task_id: str) -> dict[str, Any]:
            """Return a completed local agent task result, or report that it is still running."""
            return service.task_result(task_id)

        @mcp.tool()
        async def local_agent_run_task(
            project: str,
            source_path: str,
            objective: str,
            acceptance_criteria: list[str],
            constraints: list[str] | None = None,
            task_id: str = "",
            max_changed_lines: int = 80,
            validation_command: str = "",
            timeout_seconds: int = 180,
        ) -> dict[str, Any]:
            """Run one local coding task synchronously without blocking the FastMCP event loop."""
            return await asyncio.to_thread(
                service.run_task,
                project=project,
                source_path=source_path,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                constraints=constraints,
                task_id=task_id,
                max_changed_lines=max_changed_lines,
                validation_command=validation_command,
                timeout_seconds=timeout_seconds,
            )


def create_plugin() -> LocalAgentPlugin:
    return LocalAgentPlugin()
