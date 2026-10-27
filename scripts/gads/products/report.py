"""Product review: the Markdown review (a main output; the HTML page lives in page.py)."""
from __future__ import annotations

from gads.products.analysis import SOURCE_GRAIN, ProductReview



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
