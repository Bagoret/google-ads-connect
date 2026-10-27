"""Product review outputs: the Markdown review and the offline dashboard page."""
from __future__ import annotations

from decimal import Decimal
from html import escape

from gads.products.analysis import SOURCE_GRAIN, ProductReview
from gads.core.logbook import RunLog
from gads.core.metrics import aggregate, derive, fmt
from gads.ui.viz import badge, bar_chart, caveats_card, fold_top, page, source_note, tile


def render_product_markdown(r: ProductReview) -> str:
    snap, currency, caveats, products, definition, only_perf, only_supp, log = (
        r.snap, r.currency, r.caveats, r.products, r.definition, r.only_perf, r.only_supp, r.log)
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
    return "\n".join(L) + "\n"


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
