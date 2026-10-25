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
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.metrics import Totals, derive, fmt, group_by  # noqa: E402
from gads.normalize import records_from_snapshot, unique_dir  # noqa: E402
from gads.validate import check_single_currency, check_unique  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE_GRAIN = ("item_id", "campaign_id", "date")


def normalize_item_id(s: str) -> str:
    return str(s).strip().casefold()


def join_supplement(perf: dict[str, Totals], supplement: list[dict], log: RunLog
                    ) -> tuple[dict[str, dict], list[str], list[str]]:
    log.assume("item IDs normalised with strip + casefold on both sides before joining")
    by_id: dict[str, dict] = {}
    dupes = set()
    for item in supplement:
        key = normalize_item_id(item.get("item_id", ""))
        if not key:
            raise StopAnalysis("supplement row without item_id")
        if key in by_id:
            dupes.add(key)
        by_id[key] = item
    if dupes:
        raise StopAnalysis(f"duplicate item_id(s) in supplement would multiply revenue on join: {sorted(dupes)[:20]}")
    perf_n = {normalize_item_id(k): v for k, v in perf.items()}
    joined = {k: {"totals": t, "supplement": by_id.get(k)} for k, t in perf_n.items()}
    only_perf = sorted(k for k in perf_n if k not in by_id)
    only_supp = sorted(k for k in by_id if k not in perf_n)
    if only_perf:
        log.warn(f"{len(only_perf)} item(s) with performance but no supplement row")
    if only_supp:
        log.warn(f"{len(only_supp)} supplement item(s) with no performance in this period")
    return joined, only_perf, only_supp


def load_supplement(path: Path) -> tuple[list[dict], str | None]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items", [])
    definition = data.get("margin_definition")
    if any(i.get("margin_rate") not in (None, "") for i in items) and not definition:
        raise StopAnalysis("supplement has margin_rate values but no margin_definition; state how margin is defined")
    for i in items:
        if i.get("margin_rate") not in (None, ""):
            try:
                rate = Decimal(str(i["margin_rate"]))
            except InvalidOperation:
                raise StopAnalysis(f"invalid margin_rate for {i.get('item_id')}: {i['margin_rate']!r}")
            if not (Decimal(0) <= rate <= Decimal(1)):
                raise StopAnalysis(f"margin_rate for {i.get('item_id')} must be between 0 and 1")
    return items, definition


def run(args) -> Path:
    log = RunLog()
    snap, records = records_from_snapshot(args.products, {"item_id", "campaign_id", "date", "cost", "clicks"},
                                          log, "product_daily")
    if not records:
        raise StopAnalysis("snapshot contains no usable rows")
    check_unique(records, SOURCE_GRAIN)
    currency = check_single_currency(records, args.expected_currency)
    for r in records:
        r["item_id"] = normalize_item_id(r["item_id"])
    titles = {r["item_id"]: (r.get("product_title", ""), r.get("product_brand", "")) for r in records}
    perf = group_by(records, "item_id")
    log.assume(f"grain aggregated from {' × '.join(SOURCE_GRAIN)} to item_id × period "
               "(all campaigns in this shopping_performance_view snapshot)")

    supplement, definition = (load_supplement(args.supplement) if args.supplement else ([], None))
    joined, only_perf, only_supp = join_supplement(perf, supplement, log) if supplement else (
        {k: {"totals": t, "supplement": None} for k, t in perf.items()}, [], [])

    products = []
    for item_id, j in sorted(joined.items(), key=lambda kv: -kv[1]["totals"].cost):
        t, s = j["totals"], j["supplement"] or {}
        d = derive(t)
        row = {"item_id": item_id, "title": titles[item_id][0], "brand": titles[item_id][1],
               "cost": str(fmt(t.cost, "ratio")), "clicks": t.clicks, "conversions": fmt(t.conversions, "conv"),
               "conversion_value": fmt(t.conversion_value, "ratio"), "revenue_roas": fmt(d["roas"], "ratio"),
               "cpa": fmt(d["cpa"], "ratio")}
        if definition and s.get("margin_rate") not in (None, "") and t.conversion_value is not None:
            margin = t.conversion_value * Decimal(str(s["margin_rate"]))
            row["margin_rate"] = str(s["margin_rate"])
            row["estimated_margin"] = fmt(margin, "ratio")
            row["margin_after_ad_cost"] = fmt(margin - t.cost, "ratio")
        if s.get("stock_status"):
            row["stock_status"] = s["stock_status"]
        products.append(row)

    out = unique_dir(args.out, f"product-review_{snap.customer_id}_{snap.start}_{snap.end}")
    (out / "products.json").write_text(json.dumps({
        "source": snap.path.name, "date_range": [str(snap.start), str(snap.end)], "currency": currency,
        "synthetic": snap.synthetic, "grain": "item_id × period", "margin_definition": definition,
        "products": products, "unmatched": {"only_in_performance": only_perf, "only_in_supplement": only_supp},
        "log": log.to_dict(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    L = [f"# Product review — customer {snap.customer_id} — {snap.start} to {snap.end}", ""]
    if snap.synthetic:
        L += ["> **SYNTHETIC TEST DATA — NOT REAL.**", ""]
    L += [f"Source: `{snap.path.name}` · Currency: {currency} · Grain: item_id × period "
          f"(from {' × '.join(SOURCE_GRAIN)}) · {len(products)} items", ""]
    if definition:
        L += [f"Margin definition (supplied): {definition}. `margin_after_ad_cost` = conversion value × margin rate "
              "− ad cost; it excludes returns, shipping and other costs unless the definition includes them.", ""]
    else:
        L += ["> Revenue ROAS is **not profitability**. No margin data was supplied, so no product is labelled "
              "profitable or unprofitable.", ""]
    cols = ["item_id", "title", "brand", "cost", "clicks", "conversions", "conversion_value", "revenue_roas", "cpa"]
    extra = [c for c in ("margin_rate", "estimated_margin", "margin_after_ad_cost", "stock_status")
             if any(c in p for p in products)]
    L += ["| " + " | ".join(cols + extra) + " |", "|" + "---|" * len(cols + extra)]
    L += ["| " + " | ".join(str(p.get(c, "N/A")) for c in cols + extra) + " |" for p in products]
    L += ["", "## Join check", "",
          f"- Items with performance but no supplement row: {len(only_perf)}" + (f" ({', '.join(only_perf[:20])})" if only_perf else ""),
          f"- Supplement items with no performance: {len(only_supp)}" + (f" ({', '.join(only_supp[:20])})" if only_supp else ""),
          "", "## Validation log", ""]
    L += [f"- Assumption: {a}" for a in log.assumptions] + [f"- Warning: {w}" for w in log.warnings]
    L += [f"- Excluded row {e['index']}: {e['reason']}" for e in log.excluded]
    (out / "review.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", type=Path, required=True)
    ap.add_argument("--supplement", type=Path)
    ap.add_argument("--expected-currency")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    args = ap.parse_args(argv)
    try:
        if args.supplement:
            load_supplement(args.supplement)  # validate before anything is written
        print(run(args))
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
