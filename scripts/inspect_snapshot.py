#!/usr/bin/env python3
"""Describe a snapshot: response shape, row count, grain, fields, date range, currency,
excluded rows. Use this on every new snapshot before analysis (it is the contract gate
for the MCP response format).

Usage: python3 scripts/inspect_snapshot.py data/raw/<file>.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.core.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.core.normalize import apply_field_map, detect_grain, extract_rows, flatten_row, load_field_map, load_snapshot  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    try:
        print(json.dumps(inspect_snapshot(Path(argv[0])), indent=2, default=str))
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
