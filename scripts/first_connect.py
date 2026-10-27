#!/usr/bin/env python3
"""First-connection check: fetch every query in queries/ from your account (read-only), run the contract gate on
each response, and report which features can run. Run it once after setup, and again after any Google change.

Usage:
  python3 scripts/first_connect.py --customer-id 123-456-7890 [--end YYYY-MM-DD] [--days 14]

Dated queries cover the --days days ending on --end (default: yesterday). Raw responses are saved verbatim to
data/raw/; the report in outputs/first-connect_<customer>_<time>/ (report.md, summary.json) holds field names,
counts and statuses only, so it can be shared.
Exit codes: 0 = every query passed (or returned no rows) · 1 = at least one query failed · 2 = stopped before
running (bad customer ID, no .mcp.json).
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.connect.mcp_config import load_server_config  # noqa: E402
from gads.core.files import ROOT, unique_dir  # noqa: E402
from gads.core.ids import parse_customer_id  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402
from gads.onboarding.first_connect import run  # noqa: E402
from gads.onboarding.first_connect_report import render_markdown, summary  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--customer-id", required=True)
    ap.add_argument("--end", type=date.fromisoformat, help="last day for dated queries (default: yesterday)")
    ap.add_argument("--days", type=int, default=14, help="days covered by dated queries (default: 14)")
    ap.add_argument("--server-cmd", help="override the server command from .mcp.json (quoted string; for tests)")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        customer_id = parse_customer_id(args.customer_id)
        if not customer_id:
            raise StopAnalysis(f"not a 10-digit Google Ads customer ID: {args.customer_id!r}")
        if args.days < 1:
            raise StopAnalysis("--days must be at least 1")
        if args.server_cmd:
            cmd, env = shlex.split(args.server_cmd), {}
        else:
            cmd, env = load_server_config(ROOT / ".mcp.json")
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    end = args.end or (date.today() - timedelta(days=1))
    period = (end - timedelta(days=args.days - 1), end)
    print(f"Checking {customer_id} (read-only); dated queries {period[0]} to {period[1]}.", file=sys.stderr)
    fc = run(customer_id, period, cmd, env, args.raw_dir, progress=lambda m: print(m, file=sys.stderr))
    now = datetime.now(timezone.utc)
    out = unique_dir(args.out, f"first-connect_{customer_id}_{now.strftime('%Y%m%dT%H%M%S')}")
    (out / "report.md").write_text(render_markdown(fc, now.isoformat(timespec="seconds")), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary(fc), indent=2, ensure_ascii=False), encoding="utf-8")
    for f in fc.features:
        print(f"{f['status']:<8} {f['feature']}", file=sys.stderr)
    print(out / "report.md")
    return 1 if fc.failed else 0


if __name__ == "__main__":
    sys.exit(main())
