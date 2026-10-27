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
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.core.cli import add_common_args, load_json_file, run_cli  # noqa: E402
from gads.core.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.core.metrics import Totals, aggregate, derive, fmt, group_by  # noqa: E402
from gads.core.normalize import records_from_snapshot, unique_dir  # noqa: E402
from gads.present.viz import badge, bar_chart, caveats_card, fold_top, page, source_note, tile  # noqa: E402
from gads.core.validate import (account_timezone, check_date_coverage, check_single_currency, check_unique,  # noqa: E402
                           parse_now, partial_data_caveats)

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
    data = load_json_file(path, "supplement")
    if not isinstance(data, dict):
        raise StopAnalysis(f'supplement {path} must be an object like {{"items": [...]}}')
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


STOCK_BADGES = {"low_stock": ("warning", "●", "Low stock"), "out_of_stock": ("critical", "■", "Out of stock"),
                "preorder": ("neutral", "○", "Pre-order"), "backorder": ("neutral", "○", "Backorder")}


def render_product_dashboard(snap, currency: str, caveats: list[str], records: list[dict], joined: dict,
                             products: list[dict], definition: str | None, only_perf: list[str],
                             only_supp: list[str], log: RunLog, top_n: int = 50) -> str:
    overall = aggregate(records)
    d_all = derive(overall)
    zero_conv = [k for k, j in joined.items() if j["totals"].conversions == 0 and j["totals"].cost > 0]
    with_margin = [p for p in products if "margin_after_ad_cost" in p]
    tiles = [tile("Products", f"{len(products):,}", "with activity in the period"),
             tile("Cost", fmt(overall.cost, "money", currency)),
             tile("Conversion value", fmt(overall.conversion_value, "money", currency)),
             tile("Revenue ROAS", fmt(d_all["roas"], "ratio"), "revenue, not profit"),
             tile("Spend, no conversions", f"{len(zero_conv):,}", "products")]
    if with_margin:
        total_margin = sum((Decimal(p["margin_after_ad_cost"]) for p in with_margin), Decimal(0))
        tiles.append(tile("Margin after ad cost", fmt(total_margin, "money", currency),
                          f"{len(with_margin)} of {len(products)} products have margin data"))
    by_brand: dict[str, Decimal] = {}
    for r in records:
        name = r.get("product_brand") or "(no brand)"
        by_brand[name] = by_brand.get(name, Decimal(0)) + (r.get("cost") or Decimal(0))
    rows = []
    for p in products[:top_n]:
        t = joined[p["item_id"]]["totals"]
        flags = []
        if t.conversions == 0 and t.cost > 0:
            flags.append(badge("warning", "●", "No conversions"))
        stock = p.get("stock_status")
        if stock:
            tone, icon, label = STOCK_BADGES.get(stock, ("neutral", "○", stock.replace("_", " ").capitalize()))
            if stock != "in_stock":
                flags.append(badge(tone, icon, label))
        margin_cell = (f'<td class="num">{escape(p.get("margin_after_ad_cost", "N/A"))}</td>' if with_margin else "")
        rows.append(
            f'<tr data-item="{escape(p["item_id"])}"><td class="mono">{escape(p["item_id"])}</td>'
            f'<td class="name">{escape(p["title"])}</td><td>{escape(p["brand"])}</td>'
            f'<td class="num">{escape(fmt(t.cost, "money", currency))}</td><td class="num">{t.clicks:,}</td>'
            f'<td class="num">{escape(p["conversions"])}</td><td class="num">{escape(p["conversion_value"])}</td>'
            f'<td class="num">{escape(p["revenue_roas"])}</td>{margin_cell}<td class="name">{" ".join(flags)}</td></tr>')
    more = (f'<p class="muted small">Showing the top {top_n} of {len(products)} by cost; the full list is in '
            'products.json.</p>' if len(products) > top_n else "")
    profit_note = (f'<p class="muted small">Margin definition (supplied): {escape(definition)}. Margin after ad cost = '
                   'conversion value × margin rate − ad cost; excludes returns, shipping and other costs unless the '
                   'definition includes them.</p>' if definition else
                   '<div class="banner">Revenue ROAS is <strong>not profitability</strong>. No margin data was '
                   'supplied, so no product is labelled profitable or unprofitable.</div>')
    join = ""
    if definition or only_perf or only_supp:
        join = ('<section class="card"><h2>Join check</h2>'
                f'<p>Products with performance but no supplement row: {len(only_perf)}'
                + (f' <span class="muted small">({escape(", ".join(only_perf[:20]))})</span>' if only_perf else "")
                + f'</p><p>Supplement products with no performance: {len(only_supp)}'
                + (f' <span class="muted small">({escape(", ".join(only_supp[:20]))})</span>' if only_supp else "")
                + '</p><p class="muted small">IDs normalised with strip + casefold on both sides.</p></section>')
    margin_head = '<th class="num">Margin after ad cost</th>' if with_margin else ""
    body = f"""{profit_note}
<section class="kpis" aria-label="Key metrics">{"".join(tiles)}</section>
<section class="card"><h2>Cost by brand</h2>
{bar_chart(fold_top(list(by_brand.items()), 8), currency, "Cost by product brand", table=True)}
<p class="muted small">Product-attributed cost only. Performance Max spend outside product listings is not included;
do not add these totals to campaign totals.</p></section>
<section class="card"><h2>Products by cost</h2>
<div class="table-wrap"><table><thead><tr><th>Item ID</th><th>Title</th><th>Brand</th><th class="num">Cost</th>
<th class="num">Clicks</th><th class="num">Conv.</th><th class="num">Conv. value</th><th class="num">Revenue ROAS</th>
{margin_head}<th>Flags</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>{more}</section>
{join}
{caveats_card(caveats + log.warnings)}"""
    footer = (f"{source_note(snap)} · grain item_id × period · "
              f"{len(records)} rows · {len(log.excluded)} excluded · currency {escape(currency)}")
    return page("Product review", f"Customer {snap.customer_id} · {snap.start} to {snap.end}",
                snap.synthetic, body, footer)


def run(args) -> Path:
    log = RunLog()
    snap, records = records_from_snapshot(args.products, {"item_id", "campaign_id", "date", "cost", "clicks"},
                                          log, "product_daily", dated=True)
    if not records:
        raise StopAnalysis("snapshot contains no usable rows")
    check_unique(records, SOURCE_GRAIN)
    currency = check_single_currency(records, args.expected_currency)
    caveats = partial_data_caveats(snap.end, account_timezone(records, args.timezone), args.conversion_lag_days,
                                   parse_now(args.now))
    check_date_coverage(records, snap.start, snap.end, log)
    for r in records:
        r["item_id"] = normalize_item_id(r["item_id"])
    titles = {r["item_id"]: (r.get("product_title", ""), r.get("product_brand", ""))
              for r in sorted(records, key=lambda r: r["date"])}  # latest row wins, as in the weekly review
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
        "synthetic": snap.synthetic, "grain": "item_id × period", "caveats": caveats, "margin_definition": definition,
        "products": products, "unmatched": {"only_in_performance": only_perf, "only_in_supplement": only_supp},
        "log": log.to_dict(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    L = [f"# Product review — customer {snap.customer_id} — {snap.start} to {snap.end}", ""]
    if snap.synthetic:
        L += ["> **SYNTHETIC TEST DATA — NOT REAL.**", ""]
    L += [f"Source: `{snap.path.name}` · Currency: {currency} · Grain: item_id × period "
          f"(from {' × '.join(SOURCE_GRAIN)}) · {len(products)} items", ""]
    L += ["## Data caveats", "", *([f"- {c}" for c in caveats] or ["- None from timing."]), ""]
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
    (out / "dashboard.html").write_text(
        render_product_dashboard(snap, currency, caveats, records, joined, products, definition,
                                 only_perf, only_supp, log), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", type=Path, required=True)
    ap.add_argument("--supplement", type=Path)
    return run_cli(run, add_common_args(ap).parse_args(argv))  # run() validates the supplement before writing


if __name__ == "__main__":
    sys.exit(main())
