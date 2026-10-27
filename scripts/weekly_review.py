#!/usr/bin/env python3
"""Weekly performance review from a campaign_daily MCP snapshot.

Usage:
  python3 scripts/weekly_review.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] \
      [--expected-currency EUR] [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Only pass --conversion-lag-days / --target-* values that are recorded (not UNKNOWN) in context/.
Exit codes: 0 = done · 2 = stopped (reason printed, nothing written) · 3 = done, but an optional part was skipped
(full traceback printed; set GADS_STRICT=1 to fail loudly instead).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.weekly.analysis import add_weekly_args, build_review  # noqa: E402
from gads.core.cli import run_cli  # noqa: E402
from gads.weekly.report import render_report, write_outputs  # noqa: E402


def run_review(args: argparse.Namespace) -> Path:
    r = build_review(args)
    report = render_report(r.ctx, r.actions, r.log, r.data)
    slug = f"weekly-review_{r.ctx.customer_id}_{r.ctx.current.start}_{r.ctx.current.end}"
    return write_outputs(args.out, slug, report, r.actions, r.log, r.data.parameters)


def build_parser() -> argparse.ArgumentParser:
    return add_weekly_args(argparse.ArgumentParser(description=__doc__,
                                                   formatter_class=argparse.RawDescriptionHelpFormatter))


def main(argv: list[str] | None = None) -> int:
    return run_cli(run_review, build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
