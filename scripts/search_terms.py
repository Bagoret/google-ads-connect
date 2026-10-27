#!/usr/bin/env python3
"""Search-term review helper: brand classification, weak-performance flags, and conflicts
between negative keywords and active positive keywords. Intent judgement is left to the
search-term-review skill (Claude + human) — this script never labels a term "irrelevant".

Usage:
  python3 scripts/search_terms.py --search-terms <snap> --keywords <snap> --negatives <snap> \
      [--shared-negatives <snap> --campaign-shared-sets <snap>] [--brand-lists config/brand_lists.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.analysis.search_terms import COVERAGE_NOTE, analyse  # noqa: E402
from gads.core.cli import add_common_args, run_cli, write_optional  # noqa: E402
from gads.core.files import unique_dir  # noqa: E402
from gads.present.search_terms_page import render_search_dashboard, render_search_markdown  # noqa: E402

from gads.core.paths import ROOT  # noqa: E402


def run(args) -> Path:
    r = analyse(args)
    snap = r.snap
    out = unique_dir(args.out, f"search-terms_{snap.customer_id}_{snap.start}_{snap.end}")
    (out / "candidates.json").write_text(json.dumps({
        "source": snap.path.name, "date_range": [str(snap.start), str(snap.end)], "synthetic": snap.synthetic,
        "currency": r.currency, "caveats": r.caveats, "coverage_note": COVERAGE_NOTE, "terms": r.rows,
        "conflicts": r.conflicts, "log": r.log.to_dict(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "review.md").write_text(render_search_markdown(r), encoding="utf-8")
    write_optional(out / "dashboard.html",
                   lambda: render_search_dashboard(snap, r.currency, r.caveats, r.rows, r.conflicts, r.log), "dashboard page")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-terms", type=Path, required=True)
    ap.add_argument("--keywords", type=Path)
    ap.add_argument("--negatives", type=Path)
    ap.add_argument("--shared-negatives", type=Path)
    ap.add_argument("--campaign-shared-sets", type=Path)
    ap.add_argument("--brand-lists", type=Path, default=ROOT / "config" / "brand_lists.json")
    return run_cli(run, add_common_args(ap).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
