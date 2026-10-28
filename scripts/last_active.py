#!/usr/bin/env python3
"""Last active day: find the most recent day the account had impressions (read-only, one query), and suggest a
review period that ends on it. Use it before a review when the campaigns may be paused.

Usage:
  python3 scripts/last_active.py --customer-id 123-456-7890 [--lookback-days 365] [--days 7] [--json]

Searches the --lookback-days days ending yesterday. The raw response is saved verbatim to data/raw/.
Exit codes: 0 = found · 1 = no day with impressions in the searched period · 2 = stopped (reason printed).
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.connect.activity import DEFAULT_LOOKBACK_DAYS, find_last_active  # noqa: E402
from gads.connect.mcp_config import load_server_config  # noqa: E402
from gads.core.files import ROOT  # noqa: E402
from gads.core.ids import parse_customer_id  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--customer-id", required=True)
    ap.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                    help=f"days searched, ending yesterday (default: {DEFAULT_LOOKBACK_DAYS})")
    ap.add_argument("--days", type=int, default=7, help="length of the suggested period (default: 7)")
    ap.add_argument("--end", type=date.fromisoformat, help="last day searched (default: yesterday)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--server-cmd", help="override the server command from .mcp.json (quoted string; for tests)")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        customer_id = parse_customer_id(args.customer_id)
        if not customer_id:
            raise StopAnalysis(f"not a 10-digit Google Ads customer ID: {args.customer_id!r}")
        if not 1 <= args.lookback_days <= 3650 or args.days < 1:
            raise StopAnalysis("--lookback-days must be 1-3650 and --days at least 1")
        cmd, env = (shlex.split(args.server_cmd), {}) if args.server_cmd else load_server_config(ROOT / ".mcp.json")
        act = find_last_active(customer_id, cmd, env, args.raw_dir, args.end or date.today() - timedelta(days=1),
                               args.lookback_days)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    period = act.suggested_period(args.days)
    if args.json:
        print(json.dumps({"customer_id": customer_id, "searched": [str(d) for d in act.searched],
                          "last_active": str(act.last_active) if act.last_active else None,
                          "active_days": act.active_days,
                          "suggested_period": [str(d) for d in period] if period else None,
                          "snapshot": str(act.snapshot)}, indent=2))
    elif act.last_active is None:
        print(f"No day with impressions from {act.searched[0]} to {act.searched[1]}. "
              f"Search further back with --lookback-days (up to 3650).")
    else:
        print(f"Last day with impressions: {act.last_active} "
              f"({act.active_days} active day(s) from {act.searched[0]} to {act.searched[1]}).")
        print(f"Suggested {args.days}-day period: {period[0]} to {period[1]}  (--start {period[0]} --end {period[1]})")
    print(f"Source: {act.snapshot}", file=sys.stderr)
    return 0 if act.last_active else 1


if __name__ == "__main__":
    sys.exit(main())
