#!/usr/bin/env python3
"""Run one GAQL query from queries/ through the Google Ads MCP server and save the
verbatim response to data/raw/. Read-only: only allowlisted MCP tools can be called.

Usage:
  python3 scripts/snapshot.py --query campaign_daily --customer-id 123-456-7890 \
      --start 2026-10-06 --end 2026-10-19
The server command and env come from .mcp.json ("google-ads-mcp") unless --server-cmd is given.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.logbook import StopAnalysis  # noqa: E402
from gads.mcp_client import McpError, McpStdioClient, extract_payload  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEARCH_TOOL_NAMES = ("search_search", "search")
# Upstream googleads/google-ads-mcp `search` builds the GAQL itself from these parts.
STRUCTURED_PARAMS = {"customer_id", "fields", "resource", "conditions"}


def parse_gaql(gaql: str) -> dict:
    """Split a single-resource GAQL query into fields / resource / conditions (AND-joined)."""
    m = re.fullmatch(r"\s*SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+?))?\s*", gaql, re.I | re.S)
    if not m:
        raise StopAnalysis(f"cannot parse GAQL (only SELECT … FROM … [WHERE …] is supported): {gaql[:200]}")
    fields = [f.strip() for f in m.group(1).split(",") if f.strip()]
    conditions: list[str] = []
    for piece in re.split(r"\s+AND\s+", m.group(3) or "", flags=re.I):
        if not piece:
            continue
        if conditions and re.search(r"\bBETWEEN\s+\S+$", conditions[-1], re.I):
            conditions[-1] = f"{conditions[-1]} AND {piece}"  # rejoin "BETWEEN x AND y"
        else:
            conditions.append(piece.strip())
    return {"fields": fields, "resource": m.group(2), "conditions": conditions}


def build_search_args(input_schema: dict, customer_id: str, query: str) -> dict:
    props = set((input_schema or {}).get("properties", {}))
    if STRUCTURED_PARAMS <= props:
        parts = parse_gaql(query)
        args = {"customer_id": customer_id, "fields": parts["fields"], "resource": parts["resource"]}
        if parts["conditions"]:
            args["conditions"] = parts["conditions"]
        return args
    raise StopAnalysis(f"search tool parameters do not match the supported contract "
                       f"({sorted(STRUCTURED_PARAMS)}); server offers {sorted(props)}")


def render_query(path: Path, start: date | None, end: date | None) -> str:
    text = path.read_text(encoding="utf-8")
    needs_dates = "{start}" in text or "{end}" in text
    if needs_dates and (start is None or end is None):
        raise StopAnalysis(f"query {path.name} requires --start and --end")
    if needs_dates:
        if start > end:
            raise StopAnalysis(f"start {start} is after end {end}")
        text = text.replace("{start}", start.isoformat()).replace("{end}", end.isoformat())
    return " ".join(text.split())


def write_snapshot(path: Path, envelope: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:  # exclusive create: never overwrite raw data
        json.dump(envelope, fh, ensure_ascii=False, indent=1, default=_json_default)


def _json_default(obj):
    # Only structuredContent payloads reach here with Decimals (parsed from JSON floats
    # on the wire), so float() restores the same numeric value the server sent.
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(type(obj))


def load_server_config(path: Path) -> tuple[list[str], dict]:
    if not path.exists():
        raise StopAnalysis(f"{path} not found; copy .mcp.json.example and configure it (see docs/mcp-setup.md)")
    server = json.loads(path.read_text())["mcpServers"]["google-ads-mcp"]
    env = {k: _expand(str(v), k) for k, v in server.get("env", {}).items()}
    unset = [k for k, v in env.items() if v.startswith(("YOUR_", "PATH_TO_"))]
    if unset:
        raise StopAnalysis(f".mcp.json still has placeholder values for: {', '.join(unset)}")
    return [server["command"], *server.get("args", [])], env


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


def run_snapshot(query: str, customer_id: str, start: date | None, end: date | None,
                 server_cmd: list[str], raw_dir: Path, env: dict | None = None,
                 queries_dir: Path = ROOT / "queries") -> Path:
    customer_id = re.sub(r"\D", "", customer_id)
    if len(customer_id) != 10:
        raise StopAnalysis("customer ID must have 10 digits")
    gaql = render_query(queries_dir / f"{query}.gaql", start, end)
    fetched = datetime.now(timezone.utc)
    stamp = fetched.strftime("%Y%m%dT%H%M%S")
    span = f"{start}_{end}" if start else "nodates"
    path = raw_dir / f"{query}_{customer_id}_{span}_{stamp}.json"
    envelope = {
        "query_name": query, "gaql": gaql, "customer_id": customer_id,
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "fetched_at": fetched.isoformat(),
    }
    try:
        with McpStdioClient(server_cmd, env=env) as client:
            envelope["server_info"] = client.initialize()
            tools = {t["name"]: t for t in client.list_tools()}
            names = [n for n in SEARCH_TOOL_NAMES if n in tools]
            if not names:
                raise StopAnalysis(f"no search tool found; server offers: {sorted(tools)}")
            tool = names[0]
            arguments = build_search_args(tools[tool].get("inputSchema", {}), customer_id, gaql)
            envelope.update(tool_name=tool, tool_arguments=arguments)
            result = client.call_tool(tool, arguments)
    except McpError as exc:
        # Save what happened (message only — server stderr may hold request details), then stop.
        envelope.update(payload_kind="error", payload={"protocol_error": str(exc)})
        write_snapshot(path, envelope)
        raise StopAnalysis(f"MCP protocol failure: {exc}")
    try:
        kind, payload = extract_payload(result)
    except StopAnalysis:
        envelope.update(payload_kind="error", payload=result)
        write_snapshot(path, envelope)
        raise
    if kind == "json_text":
        # Store the server's text exactly as received; loaders re-parse it with Decimal.
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        envelope.update(payload_kind=kind, payload_text=text)
    else:
        envelope.update(payload_kind=kind, payload=payload)
    write_snapshot(path, envelope)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="query name in queries/ (without .gaql)")
    ap.add_argument("--customer-id", required=True)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--server-cmd", help="override server command (quoted string)")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args(argv)
    try:
        if args.server_cmd:
            cmd, env = shlex.split(args.server_cmd), {}
        else:
            cmd, env = load_server_config(ROOT / ".mcp.json")
        path = run_snapshot(args.query, args.customer_id, args.start, args.end, cmd, args.raw_dir, env)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
