"""Reading the "google-ads-mcp" entry of .mcp.json and recognising the server's search tool."""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

from gads.core.logbook import StopAnalysis

SEARCH_TOOL_NAMES = ("search_search", "search")
# Upstream googleads/google-ads-mcp `search` builds the GAQL itself from these parts.
STRUCTURED_PARAMS = {"customer_id", "fields", "resource", "conditions"}


def find_search_tool(tools: dict[str, dict]) -> dict | None:
    """The first known search tool the server offers (tools by name), or None."""
    return next((tools[n] for n in SEARCH_TOOL_NAMES if n in tools), None)


def server_command(override: str | None, config_path: Path) -> tuple[list[str], dict]:
    """The server command and env: the --server-cmd override (a quoted string, for tests) or .mcp.json."""
    return (shlex.split(override), {}) if override else load_server_config(config_path)


def load_server_config(path: Path) -> tuple[list[str], dict]:
    if not path.exists():
        raise StopAnalysis(f"{path} not found; copy .mcp.json.example and configure it (see docs/mcp-setup.md)")
    try:
        server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["google-ads-mcp"]
        command, args, raw_env = server["command"], server.get("args", []), server.get("env", {})
    except (ValueError, KeyError, TypeError):
        raise StopAnalysis(f"{path} is not valid: it needs mcpServers -> google-ads-mcp -> command "
                           "(compare with .mcp.json.example)")
    env = {k: _expand(str(v), k) for k, v in raw_env.items()}
    unset = [k for k, v in env.items() if v.startswith(("YOUR_", "PATH_TO_"))]
    if unset:
        raise StopAnalysis(f".mcp.json still has placeholder values for: {', '.join(unset)}")
    return [command, *args], env


def _expand(value: str, key: str) -> str:
    """Expand ${VAR} and ${VAR:-default} like Claude Code does for .mcp.json."""
    def sub(m: re.Match) -> str:
        name, default = m.group(1), m.group(3)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise StopAnalysis(f".mcp.json env {key} references unset environment variable {name}")
    return re.sub(r"\$\{(\w+)(:-([^}]*))?\}", sub, value)
