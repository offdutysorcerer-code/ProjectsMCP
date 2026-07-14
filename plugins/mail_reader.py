from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp_platform.context import PlatformContext


class MailReaderPlugin:
    """Native MCP tools for A9 Mail Reader with visible activity reporting."""

    name = "mail_reader"
    description = "Search and read A9 Mail Reader mail through its local API while reporting activity to the UI."

    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:8080"

    def _json(self, path: str, params: dict[str, Any] | None = None, method: str = "GET") -> dict[str, Any]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = self.base_url + path + (("?" + query) if query else "")
        request = Request(url, method=method, data=b"" if method == "POST" else None)
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _activity(
        self,
        action: str,
        status: str,
        message: str,
        detail: str = "",
        mail_id: str = "",
        current: int = 0,
        total: int = 0,
    ) -> None:
        try:
            self._json(
                "/api/ai/activity",
                {
                    "source": "mcp",
                    "action": action,
                    "status": status,
                    "message": message,
                    "detail": detail,
                    "mailId": mail_id,
                    "risk": "read",
                    "current": current,
                    "total": total,
                },
                "POST",
            )
        except Exception:
            pass

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        @mcp.tool()
        def mail_search(
            query: str = "",
            sender: str = "",
            recipient: str = "",
            page: int = 1,
            page_size: int = 50,
        ) -> dict[str, Any]:
            """Search A9 mail by date/subject, sender, and recipient."""
            detail = f"主旨/日期={query}；寄件人={sender}；收件人={recipient}"
            self._activity("mcp_mail_search", "running", "AI 正在搜尋郵件", detail)
            try:
                result = self._json(
                    "/api/mails",
                    {
                        "q": query,
                        "sender": sender,
                        "recipient": recipient,
                        "page": max(1, page),
                        "pageSize": max(10, min(100, page_size)),
                    },
                )
                total = int(result.get("total", 0))
                self._activity(
                    "mcp_mail_search",
                    "completed",
                    f"AI 搜尋完成，共命中 {total} 封",
                    detail,
                    current=total,
                    total=total,
                )
                return result
            except Exception as error:
                self._activity("mcp_mail_search", "failed", "AI 搜尋失敗", str(error))
                raise

        @mcp.tool()
        def mail_read(mail_id: str) -> dict[str, Any]:
            """Read one A9 mail by its exact mail ID."""
            self._activity("mcp_mail_read", "running", "AI 正在閱讀郵件", mail_id=mail_id, total=1)
            try:
                result = self._json("/api/mail", {"id": mail_id})
                self._activity(
                    "mcp_mail_read",
                    "completed",
                    "AI 已讀取郵件",
                    mail_id=mail_id,
                    current=1,
                    total=1,
                )
                return result
            except Exception as error:
                self._activity("mcp_mail_read", "failed", "AI 讀取郵件失敗", str(error), mail_id)
                raise

        @mcp.tool()
        def mail_ai_activity(after: int = 0) -> dict[str, Any]:
            """Return AI activity events and the audit log location."""
            return self._json("/api/ai/activity", {"after": max(0, after)})

        @mcp.tool()
        def mail_publish_summary(title: str, payload_json: str) -> dict[str, Any]:
            """Publish a structured AI mail summary to the A9 summary workspace."""
            json.loads(payload_json)
            self._activity("publish_summary", "running", "AI 正在發佈彙整", title)
            try:
                result = self._json("/api/ai/results", {"title": title, "payload": payload_json}, "POST")
                self._activity("publish_summary", "completed", "AI 彙整已發佈", title, current=1, total=1)
                return result
            except Exception as error:
                self._activity("publish_summary", "failed", "AI 彙整發佈失敗", str(error))
                raise

        @mcp.tool()
        def mail_list_summaries(after: int = 0) -> dict[str, Any]:
            """Return published AI mail summaries."""
            return self._json("/api/ai/results", {"after": max(0, after)})


def create_plugin() -> MailReaderPlugin:
    return MailReaderPlugin()
