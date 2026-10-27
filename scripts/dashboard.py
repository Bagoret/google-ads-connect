#!/usr/bin/env python3
"""Local performance dashboard: one self-contained HTML file (no external scripts, fonts or
requests), built from a campaign_daily snapshot with the same engine as the weekly review.

Usage:
  python3 scripts/dashboard.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] [--expected-currency EUR] \
      [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Writes outputs/dashboard_<customer>_<start>_<end>/index.html (gitignored). Open it in a browser.
Exit codes: 0 = done · 2 = stopped (reason printed, nothing written) · 3 = done, but an optional part was skipped
(full traceback printed; set GADS_STRICT=1 to fail loudly instead).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.weekly.analysis import add_weekly_args, build_review  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402
from gads.core.cli import guarded, run_cli  # noqa: E402
from gads.core.files import unique_dir  # noqa: E402
from gads.weekly.dashboard import render_dashboard  # noqa: E402

AI_UNAVAILABLE = ('<section class="card"><h2>AI analysis</h2><p class="muted">AI analysis is unavailable for this page '
                  '({}). The rest of the dashboard is unaffected.</p></section>')


def ai_parts(review, insights_path: Path | None) -> tuple[dict | None, str, str]:
    """The AI component, isolated: if it fails, the page shows a notice and the run exits 3 (see core.cli)."""
    def build():
        from gads.ai.dashboard_section import build as build_ai
        return build_ai(review, insights_path)
    return guarded("AI analysis", build,
                   lambda exc: (None, AI_UNAVAILABLE.format(escape(type(exc).__name__)), ""))


def main(argv: list[str] | None = None) -> int:
    parser = add_weekly_args(argparse.ArgumentParser(description=__doc__,
                                                     formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--insights", type=Path, help="insights.json written by Claude (validated before display)")
    return run_cli(run, parser.parse_args(argv))


def run(args) -> Path:
    if args.insights and not args.insights.is_file():
        raise StopAnalysis(f"--insights file not found: {args.insights}")
    review = build_review(args)
    facts_doc, ai_html, ai_js = ai_parts(review, args.insights)
    html = render_dashboard(review, datetime.now(timezone.utc), ai_html, ai_js)
    out = unique_dir(args.out, f"dashboard_{review.ctx.customer_id}_{review.ctx.current.start}_{review.ctx.current.end}")
    (out / "index.html").write_text(html, encoding="utf-8")
    if facts_doc is not None:
        (out / "facts.json").write_text(json.dumps(facts_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return out / "index.html"


if __name__ == "__main__":
    sys.exit(main())
