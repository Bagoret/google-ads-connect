"""Fetching one GAQL query from queries/ through the MCP server and saving the response verbatim to data/raw/.
Read-only: the client only calls allowlisted tools."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from gads.connect.mcp_client import McpError, McpStdioClient, extract_payload
from gads.connect.mcp_config import STRUCTURED_PARAMS, find_search_tool
from gads.core.files import ROOT
from gads.core.ids import require_customer_id
from gads.core.logbook import StopAnalysis


def parse_gaql(gaql: str) -> dict:
    """Split a single-resource GAQL query into fields / resource / conditions (AND-joined)."""
    if re.search(r"\b(ORDER\s+BY|LIMIT|PARAMETERS)\b", gaql, re.I):
        raise StopAnalysis("ORDER BY / LIMIT / PARAMETERS are not supported in library queries "
                           "(the MCP search tool takes them as separate arguments)")
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


def write_snapshot(path: Path, envelope: dict) -> Path:
    """Create path (or <stem>-2, -3 … if taken, e.g. by a concurrent fetch) and return the path written."""
    text = json.dumps(envelope, ensure_ascii=False, indent=1, default=_json_default)  # fail before creating the file
    path.parent.mkdir(parents=True, exist_ok=True)
    target, n = path, 1
    while True:
        try:
            with open(target, "x", encoding="utf-8") as fh:  # exclusive create: never overwrite raw data
                fh.write(text)
            return target
        except FileExistsError:
            n += 1
            target = path.with_name(f"{path.stem}-{n}{path.suffix}")


def _json_default(obj):
    # Readable copy only: Decimals in the structured payload are written as floats, which can drop digits
    # beyond ~17. Loaders read the exact numbers from "response_text" (the server's raw reply) instead.
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(type(obj))


def run_snapshot(query: str, customer_id: str, start: date | None, end: date | None,
                 server_cmd: list[str], raw_dir: Path, env: dict | None = None,
                 queries_dir: Path = ROOT / "queries") -> Path:
    customer_id = require_customer_id(customer_id)
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
            search = find_search_tool(tools)
            if not search:
                raise StopAnalysis(f"no search tool found; server offers: {sorted(tools)}")
            tool = search["name"]
            arguments = build_search_args(tools[tool].get("inputSchema", {}), customer_id, gaql)
            envelope.update(tool_name=tool, tool_arguments=arguments)
            result = client.call_tool(tool, arguments)
            response_text = client.last_response_text
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
        # Exact copy of the server's reply; "payload" is a readable but float-rounded view of it.
        envelope.update(payload_kind=kind, payload=payload, response_text=response_text)
    return write_snapshot(path, envelope)
