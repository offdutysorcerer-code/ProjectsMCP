from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, RootModel


class StatusOutput(BaseModel):
    ok: bool
    base_url: str
    service: str | None = None
    url: str | None = None
    processId: int | None = None
    error: str | None = None


class BrowserTabOutput(BaseModel):
    tabId: str
    title: str
    url: str
    canGoBack: bool
    canGoForward: bool
    isActive: bool


class TabsOutput(RootModel[list[BrowserTabOutput]]):
    pass


class NewTabOutput(BaseModel):
    tabId: str


class ActionOutput(BaseModel):
    ok: bool
    tabId: str
    status: str
    input: str | None = None


class TextOutput(BaseModel):
    ok: bool
    tabId: str
    text: str
    contentType: str
    truncated: bool


class ScreenshotOutput(BaseModel):
    ok: bool
    tabId: str
    path: str
    bytes: int


class ChatGptMessageOutput(BaseModel):
    role: str
    text: str
    messageId: str | None = None


class MessagesOutput(RootModel[list[ChatGptMessageOutput]]):
    pass


class ChatGptSendOutput(BaseModel):
    conversationUrl: str
    userMessage: ChatGptMessageOutput
    assistantMessage: ChatGptMessageOutput
    completionSignal: str
    elapsedSeconds: float


class RateLimitOutput(BaseModel):
    ok: Literal[False] = False
    status: Literal["rate_limited"] = "rate_limited"
    retryAfterSeconds: int
    error: str


class AgentOutput(BaseModel):
    name: str
    role: str
    tabId: str
    instructions: str
    initialized: bool
    createdAt: str
    updatedAt: str
    lastSentAt: str | None = None
    cooldownUntil: str | None = None
    rateLimitCount: int = 0
    tabAvailable: bool | None = None


class AgentsOutput(BaseModel):
    count: int
    agents: list[AgentOutput]


class UnregisterAgentOutput(BaseModel):
    ok: bool
    agent: AgentOutput


class AgentDispatchOutput(BaseModel):
    ok: bool
    status: Literal["ok", "cooldown", "rate_limited", "initialization_failed"]
    agent: AgentOutput
    result: ChatGptSendOutput | None = None
    initializationResult: ChatGptSendOutput | None = None
    retryAfterSeconds: int = 0
    cooldownUntil: str | None = None
    error: str | None = None
