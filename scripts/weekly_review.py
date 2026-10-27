#!/usr/bin/env python3
"""Weekly performance review from a campaign_daily MCP snapshot.

Usage:
  python3 scripts/weekly_review.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] \
      [--expected-currency EUR] [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Only pass --conversion-lag-days / --target-* values that are recorded (not UNKNOWN) in context/.
Exit code 2 = analysis stopped (reason printed); no output is written in that case.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.analysis.weekly import Review, build_review  # noqa: E402,F401  (re-exported for the dashboard and tests)
from gads.core.cli import add_common_args, run_cli  # noqa: E402
from gads.present.report import render_report, write_outputs  # noqa: E402


def run_review(args: argparse.Namespace) -> Path:
    r = build_review(args)
    report = render_report(r.ctx, r.actions, r.log, r.data)
    slug = f"weekly-review_{r.ctx.customer_id}_{r.ctx.current.start}_{r.ctx.current.end}"
    return write_outputs(args.out, slug, report, r.actions, r.log, r.data.parameters)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--current", required=True, help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--previous", help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--target-roas")
    ap.add_argument("--target-cpa")
    return add_common_args(ap)


def main(argv: list[str] | None = None) -> int:
    return run_cli(run_review, build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
