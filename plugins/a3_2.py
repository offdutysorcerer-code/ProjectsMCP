from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext
from services.a3_2_contracts import (
    ActionOutput,
    AgentDispatchOutput,
    AgentOutput,
    AgentsOutput,
    ChatGptMessageOutput,
    ChatGptSendOutput,
    MessagesOutput,
    NewTabOutput,
    RateLimitOutput,
    ScreenshotOutput,
    StatusOutput,
    TabsOutput,
    TextOutput,
    UnregisterAgentOutput,
)
from services.a3_2_service import A3_2RateLimitError


class A3_2Plugin:
    name = "a3_2"
    description = "Control the local A3_2 WebView2 runtime and its authenticated ChatGPT tabs."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        service = context.a3_2_service

        @mcp.tool(structured_output=True)
        async def a3_2_status() -> StatusOutput:
            """Check whether the local A3_2 WebView2 control API is reachable."""
            return StatusOutput.model_validate(await service.status())

        @mcp.tool(structured_output=True)
        async def a3_2_list_tabs() -> TabsOutput:
            """List A3_2 tabs using their process-stable GUID tab IDs."""
            return TabsOutput.model_validate(await service.list_tabs())

        @mcp.tool(structured_output=True)
        async def a3_2_new_tab(url: str = "", activate: bool = True) -> NewTabOutput:
            """Create an A3_2 WebView2 tab and optionally navigate it to a URL."""
            return NewTabOutput.model_validate(await service.new_tab(url, activate))

        @mcp.tool(structured_output=True)
        async def a3_2_close_tab(tab_id: str) -> ActionOutput:
            """Close an A3_2 tab by GUID tab ID."""
            return ActionOutput.model_validate(await service.close_tab(tab_id))

        @mcp.tool(structured_output=True)
        async def a3_2_activate_tab(tab_id: str) -> ActionOutput:
            """Activate an A3_2 tab by GUID tab ID."""
            return ActionOutput.model_validate(await service.activate_tab(tab_id))

        @mcp.tool(structured_output=True)
        async def a3_2_navigate(tab_id: str, input: str) -> ActionOutput:
            """Navigate an A3_2 tab to a URL or search input."""
            return ActionOutput.model_validate(await service.navigate(tab_id, input))

        @mcp.tool(structured_output=True)
        async def a3_2_get_text(tab_id: str, max_chars: int = 12000) -> TextOutput:
            """Read visible body text from an A3_2 tab."""
            return TextOutput.model_validate(await service.get_text(tab_id, max_chars))

        @mcp.tool(structured_output=True)
        async def a3_2_screenshot(tab_id: str) -> ScreenshotOutput:
            """Save a PNG screenshot from an A3_2 tab and return the local artifact path."""
            return ScreenshotOutput.model_validate(await service.screenshot(tab_id))

        @mcp.tool(structured_output=True)
        async def a3_2_chatgpt_send_message(
            tab_id: str,
            message: str,
            timeout_seconds: int = 120,
        ) -> ChatGptSendOutput | RateLimitOutput:
            """Send a message to a ChatGPT tab; reports rate_limited instead of blindly retrying."""
            try:
                result = await service.chatgpt_send_message(tab_id, message, timeout_seconds)
                return ChatGptSendOutput.model_validate(result)
            except A3_2RateLimitError as exc:
                return RateLimitOutput(
                    retryAfterSeconds=exc.retry_after_seconds,
                    error=str(exc),
                )

        @mcp.tool(structured_output=True)
        async def a3_2_chatgpt_get_messages(tab_id: str) -> MessagesOutput:
            """Read user and assistant messages from an A3_2 ChatGPT conversation tab."""
            return MessagesOutput.model_validate(await service.chatgpt_get_messages(tab_id))

        @mcp.tool(structured_output=True)
        async def a3_2_chatgpt_get_last_response(tab_id: str) -> ChatGptMessageOutput:
            """Return the latest assistant message from an A3_2 ChatGPT conversation tab."""
            return ChatGptMessageOutput.model_validate(await service.chatgpt_get_last_response(tab_id))

        @mcp.tool(structured_output=True)
        async def a3_2_register_agent(
            name: str,
            role: str,
            tab_id: str,
            instructions: str = "",
        ) -> AgentOutput:
            """Register a logical agent name and role to an existing A3_2 tab ID."""
            return AgentOutput.model_validate(
                await service.register_agent(name, role, tab_id, instructions)
            )

        @mcp.tool(structured_output=True)
        async def a3_2_list_agents() -> AgentsOutput:
            """List registered agents, tab availability, and cooldown/backoff state."""
            return AgentsOutput.model_validate(await service.list_agents())

        @mcp.tool(structured_output=True)
        async def a3_2_unregister_agent(name: str) -> UnregisterAgentOutput:
            """Remove an A3_2 agent registration without closing its browser tab."""
            return UnregisterAgentOutput.model_validate(await service.unregister_agent(name))

        @mcp.tool(structured_output=True)
        async def a3_2_initialize_agent(
            name: str,
            timeout_seconds: int = 120,
        ) -> AgentDispatchOutput:
            """Initialize an agent; respects global/per-agent cooldown and rate-limit backoff."""
            return AgentDispatchOutput.model_validate(
                await service.initialize_agent(name, timeout_seconds)
            )

        @mcp.tool(structured_output=True)
        async def a3_2_send_to_agent(
            name: str,
            message: str,
            timeout_seconds: int = 120,
        ) -> AgentDispatchOutput:
            """Dispatch work by logical agent name with cooldown/backoff protection."""
            return AgentDispatchOutput.model_validate(
                await service.send_to_agent(name, message, timeout_seconds)
            )


def create_plugin() -> A3_2Plugin:
    return A3_2Plugin()
