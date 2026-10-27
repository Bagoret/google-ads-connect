#!/usr/bin/env python3
"""Product (item) performance review from a product_daily MCP snapshot, with optional
margin/stock supplement. Never calls a product profitable from revenue ROAS alone.

Usage:
  python3 scripts/product_review.py --products <product_daily snapshot> [--supplement margins.json]

Supplement format (JSON, supplied by the business):
  {"margin_definition": "...", "items": [{"item_id": "...", "margin_rate": "0.35", "stock_status": "in_stock"}]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.analysis.products import analyse, join_supplement, normalize_item_id  # noqa: E402,F401
from gads.core.cli import add_common_args, run_cli, write_optional  # noqa: E402
from gads.core.normalize import unique_dir  # noqa: E402
from gads.present.products_page import render_product_dashboard, render_product_markdown  # noqa: E402


def run(args) -> Path:
    r = analyse(args)
    snap = r.snap
    out = unique_dir(args.out, f"product-review_{snap.customer_id}_{snap.start}_{snap.end}")
    (out / "products.json").write_text(json.dumps({
        "source": snap.path.name, "date_range": [str(snap.start), str(snap.end)], "currency": r.currency,
        "synthetic": snap.synthetic, "grain": "item_id × period", "caveats": r.caveats, "margin_definition": r.definition,
        "products": r.products, "unmatched": {"only_in_performance": r.only_perf, "only_in_supplement": r.only_supp},
        "log": r.log.to_dict(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "review.md").write_text(render_product_markdown(r), encoding="utf-8")
    write_optional(out / "dashboard.html",
                   lambda: render_product_dashboard(snap, r.currency, r.caveats, r.records, r.joined, r.products,
                                                    r.definition, r.only_perf, r.only_supp, r.log))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", type=Path, required=True)
    ap.add_argument("--supplement", type=Path)
    return run_cli(run, add_common_args(ap).parse_args(argv))  # run() validates the supplement before writing


if __name__ == "__main__":
    sys.exit(main())
