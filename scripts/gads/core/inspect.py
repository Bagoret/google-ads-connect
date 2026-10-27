"""The contract gate: describe a snapshot's response shape, rows, grain, fields, date range and currency, so a
change in Google's response format is noticed before any analysis runs."""
from __future__ import annotations

from pathlib import Path

from gads.core.logbook import RunLog
from gads.core.normalize import apply_field_map, detect_grain, extract_rows, flatten_row, load_field_map, load_snapshot


def inspect_snapshot(path: Path) -> dict:
    snap = load_snapshot(path)
    log = RunLog()
    raw_rows = extract_rows(snap.payload, log)
    flat = [flatten_row(r) for r in raw_rows]
    records = apply_field_map(flat, load_field_map(), set(), log)
    dates = sorted({r["date"] for r in records if r.get("date")})
    return {
        "file": str(path),
        "synthetic": snap.synthetic,
        "query_name": snap.query_name,
        "customer_id": snap.customer_id,
        "requested_range": [str(snap.start) if snap.start else None, str(snap.end) if snap.end else None],
        "fetched_at": snap.fetched_at,
        "rows": len(records),
        "raw_fields": sorted({k for r in flat for k in r}),
        "canonical_fields": sorted({k for r in records for k in r}),
        "grain": detect_grain(records),
        "date_range": [str(dates[0]), str(dates[-1])] if dates else None,
        "currencies": sorted({r["currency"] for r in records if r.get("currency")}),
        "log": log.to_dict(),
    }
