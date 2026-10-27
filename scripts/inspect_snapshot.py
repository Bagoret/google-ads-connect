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

from gads.core.inspect import inspect_snapshot  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    if not Path(argv[0]).is_file():
        print(f"STOP: snapshot not found: {argv[0]}", file=sys.stderr)
        return 2
    try:
        print(json.dumps(inspect_snapshot(Path(argv[0])), indent=2, default=str))
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
