"""Load MCP snapshots and normalise GAQL rows into canonical, typed records."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gads.core.logbook import RunLog, StopAnalysis
from gads.core.paths import ROOT

MICROS = Decimal(1_000_000)


@dataclass
class Snapshot:
    path: Path
    query_name: str
    gaql: str
    customer_id: str
    start: date | None
    end: date | None
    fetched_at: str
    synthetic: bool
    payload: object


def load_field_map(path: Path = ROOT / "config" / "field_map.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(path: Path) -> Snapshot:
    env = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal)
    kind = env.get("payload_kind")
    if kind == "error":
        raise StopAnalysis(f"snapshot {Path(path).name} holds an MCP error result, not data")
    if kind == "json_text":
        payload = json.loads(env["payload_text"], parse_float=Decimal)
    elif kind == "structured" and env.get("response_text"):  # exact numbers from the raw reply
        payload = json.loads(env["response_text"], parse_float=Decimal)["result"]["structuredContent"]
    elif kind == "structured":
        payload = env["payload"]
    else:
        raise StopAnalysis(f"snapshot {Path(path).name} has unknown payload_kind {kind!r}")
    return Snapshot(
        path=Path(path), query_name=env["query_name"], gaql=env["gaql"], customer_id=env["customer_id"],
        start=date.fromisoformat(env["start"]) if env.get("start") else None,
        end=date.fromisoformat(env["end"]) if env.get("end") else None,
        fetched_at=env.get("fetched_at", ""), synthetic="_synthetic" in env, payload=payload,
    )


def extract_rows(payload: object, log: RunLog) -> list[dict]:
    if isinstance(payload, dict):
        token = payload.get("nextPageToken") or payload.get("next_page_token")
        if token:
            raise StopAnalysis("response is paginated (nextPageToken present); refusing to analyse a partial result")
        for key in ("result", "results", "rows"):  # "result": FastMCP wraps list returns
            if isinstance(payload.get(key), list):
                log.assume(f"rows read from response key '{key}'")
                payload = payload[key]
                break
        else:
            raise StopAnalysis(f"unknown response shape: dict with keys {sorted(payload)[:10]}")
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise StopAnalysis(f"unknown response shape: {type(payload).__name__}")
    return payload


def _snake(segment: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", segment).lower()


def flatten_row(row: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in row.items():
        path = ".".join(_snake(part) for part in key.split("."))
        path = f"{prefix}.{path}" if prefix else path
        if isinstance(value, dict):
            out.update(flatten_row(value, path))
        else:
            out[path] = value
    return out


def _convert(value: object, kind: str) -> object:
    if value is None:
        return None
    if kind == "str":
        return ("true" if value else "false") if isinstance(value, bool) else str(value)
    if kind == "id":
        text = str(value)
        if not text.isdigit():
            raise ValueError(f"id is not numeric: {text!r}")
        return text
    if kind == "date":
        return date.fromisoformat(str(value))
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}")
    if not number.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    if kind == "int":
        if number != number.to_integral_value():
            raise ValueError(f"expected integer: {value!r}")
        return int(number)
    if kind == "micros":
        return number / MICROS
    if kind == "decimal":
        return number
    raise ValueError(f"unknown field type {kind}")


def apply_field_map(rows: list[dict], field_map: dict, required: set[str], log: RunLog) -> list[dict]:
    present = {field_map[key]["name"] for r in rows for key in r if key in field_map}
    missing_everywhere = sorted(required - present) if rows else []
    if missing_everywhere:
        raise StopAnalysis(f"required field(s) missing from response: {', '.join(missing_everywhere)}")
    unmapped: set[str] = set()
    records: list[dict] = []
    for i, row in enumerate(rows):
        rec: dict[str, object] = {}
        bad = None
        for key, value in row.items():
            spec = field_map.get(key)
            if spec is None:
                unmapped.add(key)
                continue
            try:
                rec[spec["name"]] = _convert(value, spec["type"])
            except ValueError as exc:
                bad = f"{key}: {exc}"
                break
        if bad is None:
            lacking = sorted(n for n in required if rec.get(n) is None)
            if lacking:
                bad = f"missing required value(s): {', '.join(lacking)}"
        if bad:
            log.exclude(i, bad, row)
            continue
        records.append(rec)
    for key in sorted(unmapped):
        log.warn(f"unmapped field ignored: {key} (add it to config/field_map.json to use it)")
    return records


# Dimension fields, in display order. A record set's grain is the subset present.
GRAIN_DIMENSIONS = [
    "customer_id", "campaign_id", "ad_group_id", "criterion_id", "shared_set_id",
    "conversion_action_id", "search_term", "matched_keyword_text", "matched_keyword_match_type",
    "item_id", "date",
]


def detect_grain(records: list[dict]) -> list[str]:
    present = {k for r in records for k in r}
    return [d for d in GRAIN_DIMENSIONS if d in present]


def records_from_snapshot(path: Path, required: set[str], log: RunLog,
                          expected_query: str | None = None, dated: bool = False) -> tuple[Snapshot, list[dict]]:
    """Load a snapshot and return its typed records (shared by all review scripts)."""
    snap = load_snapshot(path)
    if expected_query and snap.query_name != expected_query:
        raise StopAnalysis(f"{Path(path).name} is a {snap.query_name} snapshot; expected {expected_query}")
    if dated and (snap.start is None or snap.end is None):
        raise StopAnalysis(f"{Path(path).name} has no start/end date range; re-fetch it with scripts/snapshot.py")
    rows = [flatten_row(r) for r in extract_rows(snap.payload, log)]
    return snap, apply_field_map(rows, load_field_map(), required, log)
