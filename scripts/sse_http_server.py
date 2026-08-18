#!/usr/bin/env python3
"""Minimal MCP server over HTTP+SSE for testing LM Studio's URL-based MCP client.

Endpoints:
  GET  /sse      -> SSE stream; first event is `endpoint` with the message POST url
  POST /message  -> receives JSON-RPC requests, replies are pushed on the SSE stream

Only stdlib is used. Supports: initialize, tools/list, tools/call (ping), ping.
"""

import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class ClientSession:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.queue = []  # list of (event_type, data_str)
        self.cond = threading.Condition()

    def push(self, event_type, data):
        with self.cond:
            self.queue.append((event_type, data))
            self.cond.notify_all()


SESSIONS = {}


def handle_rpc(req):
    """Process one JSON-RPC request dict; return response dict or None for notifications."""
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "projects-mcp-sse-test", "version": "0.1.0"},
        }
    elif method == "notifications/initialized" or (method or "").startswith("notifications/"):
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "ping",
                    "description": "Return a pong string to prove the MCP link works.",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        }
    elif method == "tools/call":
        args = req.get("params", {}).get("arguments", {}) or {}
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"pong from projects-mcp-sse-test (arg={args!r})",
                }
            ]
        }
    else:
        if rid is None:
            return None
        result = {"error": {"code": -32601, "message": f"Method not found: {method}"}}

    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logging to stdout
        sys.stdout.write("[sse-server] " + (fmt % args) + "\n")
        sys.stdout.flush()

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/sse":
            self.send_error(404, "not found")
            return

        session = ClientSession()
        SESSIONS[session.session_id] = session
        self.log_message("SSE client connected: %s", session.session_id)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # First event: tell the client where to POST messages.
        endpoint_url = f"/message?session_id={session.session_id}"
        try:
            self.wfile.write(f"event: endpoint\ndata: {endpoint_url}\n\n".encode("utf-8"))
            self.wfile.flush()

            while True:
                with session.cond:
                    if not session.queue:
                        session.cond.wait(timeout=15)
                    items = list(session.queue)
                    session.queue.clear()
                for event_type, data in items:
                    self.wfile.write(f"event: {event_type}\ndata: {data}\n\n".encode("utf-8"))
                if not items:
                    # keep-alive comment so proxies/clients don't time out
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            SESSIONS.pop(session.session_id, None)
            self.log_message("SSE client disconnected: %s", session.session_id)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/message":
            self.send_error(404, "not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self._send_json({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": f"parse error: {exc}"}}, 400)
            return

        session_id = ""
        qs = parsed.query
        for part in qs.split("&"):
            if part.startswith("session_id="):
                session_id = part[len("session_id="):]
        session = SESSIONS.get(session_id)

        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

        resp = handle_rpc(req)
        if resp is None or session is None:
            return
        with session.cond:
            session.queue.append(("message", json.dumps(resp)))
            session.cond.notify_all()


def main():
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[sse-server] MCP SSE test server listening on http://127.0.0.1:{port}/sse", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
