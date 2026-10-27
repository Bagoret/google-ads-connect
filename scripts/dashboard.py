#!/usr/bin/env python3
"""Local performance dashboard: one self-contained HTML file (no external scripts, fonts or
requests), built from a campaign_daily snapshot with the same engine as the weekly review.

Usage:
  python3 scripts/dashboard.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] [--expected-currency EUR] \
      [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Writes outputs/dashboard_<customer>_<start>_<end>/index.html (gitignored). Open it in a browser.
Exit code 2 = analysis stopped (reason printed); nothing is written in that case.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.analysis.weekly import add_weekly_args, build_review  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402
from gads.core.files import unique_dir  # noqa: E402
from gads.present.weekly_dashboard import render_dashboard  # noqa: E402

AI_UNAVAILABLE = ('<section class="card"><h2>AI analysis</h2><p class="muted">AI analysis is unavailable for this page '
                  '({}). The rest of the dashboard is unaffected.</p></section>')


def ai_parts(review, insights_path: Path | None) -> tuple[dict | None, str, str]:
    """The AI component, isolated: any error here becomes a notice on the page instead of a failed build."""
    try:
        from gads.ai.dashboard_section import build
        return build(review, insights_path)
    except Exception as exc:  # noqa: BLE001 - deliberate fault isolation
        print(f"Warning: AI analysis skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None, AI_UNAVAILABLE.format(escape(type(exc).__name__)), ""


def main(argv: list[str] | None = None) -> int:
    parser = add_weekly_args(argparse.ArgumentParser(description=__doc__,
                                                     formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--insights", type=Path, help="insights.json written by Claude (validated before display)")
    args = parser.parse_args(argv)
    if args.insights and not args.insights.is_file():
        print(f"STOP: --insights file not found: {args.insights}", file=sys.stderr)
        return 2
    try:
        review = build_review(args)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    facts_doc, ai_html, ai_js = ai_parts(review, args.insights)
    html = render_dashboard(review, datetime.now(timezone.utc), ai_html, ai_js)
    out = unique_dir(args.out, f"dashboard_{review.ctx.customer_id}_{review.ctx.current.start}_{review.ctx.current.end}")
    (out / "index.html").write_text(html, encoding="utf-8")
    if facts_doc is not None:
        (out / "facts.json").write_text(json.dumps(facts_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
