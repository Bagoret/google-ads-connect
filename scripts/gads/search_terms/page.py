"""Search-term review: the offline dashboard page (optional output, loaded behind the guard in search_terms.py)."""
from __future__ import annotations

from decimal import Decimal
from html import escape

from gads.core.logbook import RunLog
from gads.core.metrics import fmt
from gads.search_terms.analysis import COVERAGE_NOTE
from gads.ui.viz import badge, bar_chart, caveats_card, page, source_note, tile



def render_search_dashboard(snap, currency: str, caveats: list[str], rows: list[dict], conflicts: list[dict],
                            log: RunLog, top_n: int = 50) -> str:
    total = sum((Decimal(r["cost"]) for r in rows), Decimal(0))
    conv = sum((Decimal(r["conversions"]) for r in rows if r["conversions"] is not None), Decimal(0))
    weak = [r for r in rows if r["weak_performance"]]
    by_class: dict[str, Decimal] = {}
    for r in rows:
        by_class[r["brand_class"]] = by_class.get(r["brand_class"], Decimal(0)) + Decimal(r["cost"])
    tiles = "".join([
        tile("Search terms", f"{len(rows):,}", "campaign × term rows"),
        tile("Cost covered", fmt(total, "money", currency)),
        tile("Conversions", fmt(conv, "conv")),
        tile("Weak performance", f"{len(weak):,}", "flagged by thresholds"),
        tile("Conflicting exclusions", f"{len(conflicts):,}", "negatives blocking keywords"),
    ])
    term_rows = []
    for r in rows[:top_n]:
        flags = []
        if r["weak_performance"]:
            flags.append(badge("warning", "●", "Weak performance"))
        flags.append(badge("neutral", "○", "Intent review pending"))
        term_rows.append(
            f'<tr><td>{escape(r["search_term"])}</td><td class="mono">{escape(r["campaign_id"])}</td>'
            f'<td>{escape(r["brand_class"])}</td><td class="num">{r["clicks"]:,}</td>'
            f'<td class="num">{escape(fmt(Decimal(r["cost"]), "money", currency))}</td>'
            f'<td class="num">{fmt(None if r["conversions"] is None else Decimal(r["conversions"]), "conv")}</td>'
            f'<td class="name">{" ".join(flags)}'
            + (f'<div class="muted small">{escape(r["weak_performance"])}</div>' if r["weak_performance"] else "")
            + "</td></tr>")
    more = (f'<p class="muted small">Showing the top {top_n} of {len(rows)} by cost; the full list is in '
            'candidates.json.</p>' if len(rows) > top_n else "")
    conflict_items = "".join(
        f'<li class="issue">{badge("critical", "■", "Conflict")}<div><div class="issue-title">'
        f'{escape(c["negative_level"])} negative "{escape(c["negative_text"])}" ({escape(c["negative_match_type"])}) '
        f'blocks keyword "{escape(c["keyword_text"])}" ({escape(c["keyword_match_type"])})</div>'
        f'<div class="muted small">Campaign {escape(c["campaign_id"])} · keyword {escape(str(c["keyword_criterion_id"]))}'
        f' · approximate check (close variants and accents not modelled)</div></div></li>' for c in conflicts)
    body = f"""
<div class="banner">{escape(COVERAGE_NOTE)}</div>
<section class="kpis" aria-label="Key metrics">{tiles}</section>
<section class="card"><h2>Cost by brand class</h2>
{bar_chart(list(by_class.items()), currency, "Cost by brand class", table=True)}
<p class="muted small">Classes come from config/brand_lists.json. generic_or_unknown = no listed brand matched;
it is not a judgement of relevance.</p></section>
<section class="card"><h2>Conflicting exclusions</h2>
{('<ul class="issues">' + conflict_items + '</ul>') if conflicts else '<p class="muted">None found.</p>'}</section>
<section class="card"><h2>Search terms by cost</h2>
<p class="muted small">Weak performance is not the same as irrelevant intent. Negative keywords are candidates
for your review; nothing is added to the account.</p>
<div class="table-wrap"><table><thead><tr><th>Search term</th><th>Campaign</th><th>Brand class</th>
<th class="num">Clicks</th><th class="num">Cost</th><th class="num">Conv.</th><th>Flags</th></tr></thead>
<tbody>{"".join(term_rows)}</tbody></table></div>{more}</section>
{caveats_card(caveats + log.warnings)}"""
    footer = (f"{source_note(snap)} · {len(rows)} rows · "
              f"{len(log.excluded)} excluded · currency {escape(currency)}")
    return page("Search-term review", f"Customer {snap.customer_id} · {snap.start} to {snap.end}",
                snap.synthetic, body, footer)
