"""Search-term review: the Markdown review (a main output; the HTML page lives in page.py)."""
from __future__ import annotations

from decimal import Decimal

from gads.core.metrics import fmt
from gads.search_terms.analysis import COVERAGE_NOTE, SearchTermReview



def render_search_markdown(r: SearchTermReview) -> str:
    snap, currency, caveats, grain, rows, conflicts, log = (r.snap, r.currency, r.caveats, r.grain, r.rows,
                                                            r.conflicts, r.log)
    L = [f"# Search-term review — customer {snap.customer_id} — {snap.start} to {snap.end}", ""]
    if snap.synthetic:
        L += ["> **SYNTHETIC TEST DATA — NOT REAL.**", ""]
    L += [f"Source: `{snap.path.name}` · Currency: {currency} · {len(rows)} campaign × term rows · "
          f"grain {' × '.join(grain)}", "", f"> {COVERAGE_NOTE}", "", "## Data caveats", "",
          *([f"- {c}" for c in caveats] or ["- None from timing."]), "",
          "## Terms (by cost)", "", "Intent review is PENDING — weak performance is not the same as irrelevant intent.", "",
          "| Campaign | Search term | Brand class | Clicks | Cost | Conv. | Weak-performance flag | Intent review |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['campaign_id']} | {r['search_term']} | {r['brand_class']} | {r['clicks']} | "
                 f"{fmt(Decimal(r['cost']), 'money', currency)} | {r['conversions'] or 'N/A'} | {r['weak_performance'] or '–'} | PENDING |")
    L += ["", "## Conflicting exclusions (approximate)", "",
          "Negatives that would block an active keyword's own text. Close variants and accents are not modelled.", ""]
    L += [f"- {c['negative_level']} negative \"{c['negative_text']}\" ({c['negative_match_type']}) blocks keyword "
          f"\"{c['keyword_text']}\" ({c['keyword_match_type']}) — campaign {c['campaign_id']}, keyword {c['keyword_criterion_id']}"
          for c in conflicts] or ["- None found."]
    L += ["", "## Validation log", ""]
    L += [f"- {w}" for w in log.warnings] + [f"- Excluded row {e['index']}: {e['reason']}" for e in log.excluded] or ["- Clean."]
    return "\n".join(L) + "\n"
