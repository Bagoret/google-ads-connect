"""Minimal MCP client over stdio (newline-delimited JSON-RPC 2.0), standard library only.

Only read tools in ALLOWED_TOOLS can be called. Anything else raises ToolNotAllowed
before a request is sent.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from decimal import Decimal

from .logbook import StopAnalysis

PROTOCOL_VERSION = "2025-06-18"

ALLOWED_TOOLS = frozenset({
    "search",
    "list_accessible_customers",
    "get_resource_metadata",
    "search_search",
    "customers_list_accessible_customers",
    "metadata_get_resource_metadata",
})


class ToolNotAllowed(Exception):
    pass


class McpError(Exception):
    """Protocol-level failure. The server's stderr is kept in .stderr_tail, never in the message,
    because it can contain request details."""

    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


class McpStdioClient:
    def __init__(self, command: list[str], env: dict[str, str] | None = None, timeout_s: float = 120):
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._next_id = 1
        self._stderr = tempfile.TemporaryFile(mode="w+")
        self.last_response_text = ""  # the raw JSON-RPC line of the last answered request, kept verbatim

    def __enter__(self) -> "McpStdioClient":
        try:
            self._proc = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
                env=self.env, text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            self._stderr.close()
            raise McpError(f"cannot start the MCP server ({type(exc).__name__}: {exc.strerror or exc})")
        threading.Thread(target=self._pump, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._stderr.close()

    def _pump(self) -> None:
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _stderr_tail(self) -> str:
        try:
            self._stderr.seek(0)
            return self._stderr.read()[-2000:]
        except Exception:
            return ""

    def _send(self, message: dict) -> None:
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except OSError:  # the server exited before reading (BrokenPipeError)
            raise McpError(f"server is not accepting requests ({message.get('method')})", self._stderr_tail())

    def _request(self, method: str, params: dict) -> dict:
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout_s  # one deadline per request, however many notifications arrive
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise queue.Empty
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise McpError(f"timeout waiting for {method}", self._stderr_tail())
            if line is None:
                raise McpError(f"server exited during {method}", self._stderr_tail())
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line, parse_float=Decimal)
            except json.JSONDecodeError:
                continue  # non-protocol output on stdout; ignore
            if msg.get("id") != req_id:
                continue  # notifications or unrelated messages
            if "error" in msg:
                raise McpError(f"{method} failed: {msg['error']}")
            self.last_response_text = line
            return msg.get("result", {})

    def initialize(self) -> dict:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "google-ads-os", "version": "0.1"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result.get("serverInfo", {})

    def list_tools(self) -> list[dict]:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED_TOOLS:
            raise ToolNotAllowed(f"tool '{name}' is not in the read-only allowlist")
        return self._request("tools/call", {"name": name, "arguments": arguments})


def extract_payload(result: dict) -> tuple[str, object]:
    """Return ("structured", obj) or ("json_text", obj); stop on errors or non-JSON text."""
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    if result.get("isError"):
        raise StopAnalysis("MCP tool returned an error: " + " | ".join(texts)[:2000])
    if "structuredContent" in result and result["structuredContent"] is not None:
        return "structured", result["structuredContent"]
    if not texts:
        raise StopAnalysis("MCP tool result has no structuredContent and no text content")
    try:
        return "json_text", json.loads(texts[0], parse_float=Decimal)
    except json.JSONDecodeError:
        raise StopAnalysis("MCP tool returned text that is not JSON: " + texts[0][:500])
