from __future__ import annotations

import asyncio
from typing import Any

from mcp_platform.context import PlatformContext


class CodexAgentPlugin:
    name = "codex_agent"
    description = "Dispatch coding tasks to the OpenAI Codex CLI."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.codex_agent_service

        @mcp.tool()
        def codex_agent_status() -> dict[str, Any]:
            return service.status()

        @mcp.tool()
        def codex_agent_submit_task(project: str, working_path: str, objective: str, acceptance_criteria: list[str], constraints: list[str] | None = None, task_id: str = "", sandbox: str = "workspace-write", model: str = "", timeout_seconds: int = 900) -> dict[str, Any]:
            return service.submit_task(project=project, working_path=working_path, objective=objective, acceptance_criteria=acceptance_criteria, constraints=constraints, task_id=task_id, sandbox=sandbox, model=model, timeout_seconds=timeout_seconds)

        @mcp.tool()
        def codex_agent_task_status(task_id: str) -> dict[str, Any]:
            return service.task_status(task_id)

        @mcp.tool()
        def codex_agent_task_result(task_id: str) -> dict[str, Any]:
            return service.task_result(task_id)

        @mcp.tool()
        async def codex_agent_run_task(project: str, working_path: str, objective: str, acceptance_criteria: list[str], constraints: list[str] | None = None, task_id: str = "", sandbox: str = "workspace-write", model: str = "", timeout_seconds: int = 900) -> dict[str, Any]:
            return await asyncio.to_thread(service.run_task, project=project, working_path=working_path, objective=objective, acceptance_criteria=acceptance_criteria, constraints=constraints, task_id=task_id, sandbox=sandbox, model=model, timeout_seconds=timeout_seconds)


def create_plugin() -> CodexAgentPlugin:
    return CodexAgentPlugin()
