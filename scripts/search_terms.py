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
import re
import sys
import unicodedata
from html import escape
from decimal import Decimal
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.metrics import fmt, group_by  # noqa: E402
from gads.normalize import records_from_snapshot, unique_dir  # noqa: E402
from gads.viz import badge, bar_chart, page, tile  # noqa: E402
from gads.validate import account_timezone, check_single_currency, check_unique, parse_now, partial_data_caveats  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_NOTE = ("The search-terms data does not include every search query: Google withholds low-volume "
                 "and privacy-thresholded queries, and Performance Max terms are not in this report.")


def normalize_term(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _tokens(text: str, strip_accents: bool = False) -> list[str]:
    text = re.sub(r'[\[\]"+]', " ", text)
    return (normalize_term(text) if strip_accents else " ".join(text.casefold().split())).split()


def classify_brand(term: str, lists: dict[str, list[str]]) -> Literal["marketplace", "stocked", "competitor", "generic_or_unknown"]:
    padded = f" {normalize_term(term)} "
    for label in ("marketplace", "stocked", "competitor"):
        for name in lists.get(label, []):
            if name and f" {normalize_term(name)} " in padded:
                return label
    return "generic_or_unknown"


def negative_blocks(neg_text: str, neg_match: Literal["EXACT", "PHRASE", "BROAD"], kw_text: str) -> bool:
    """Approximate: would this negative block the keyword's own text as a query?
    Case-insensitive; accents, plurals and other close variants are NOT modelled."""
    neg, kw = _tokens(neg_text), _tokens(kw_text)
    if not neg:
        return False
    if neg_match == "EXACT":
        return neg == kw
    if neg_match == "PHRASE":
        return any(kw[i:i + len(neg)] == neg for i in range(len(kw) - len(neg) + 1))
    if neg_match == "BROAD":
        return set(neg) <= set(kw)
    raise ValueError(f"unknown match type {neg_match}")


def find_conflicts(negatives: list[dict], keywords: list[dict]) -> list[dict]:
    conflicts = []
    for neg in negatives:
        scope = set(neg.get("scope_campaign_ids") or [])
        for kw in keywords:
            if kw["campaign_id"] not in scope:
                continue
            if neg.get("ad_group_id") and neg["ad_group_id"] != kw.get("ad_group_id"):
                continue
            if negative_blocks(neg["keyword_text"], neg["match_type"], kw["keyword_text"]):
                conflicts.append({
                    "negative_text": neg["keyword_text"], "negative_match_type": neg["match_type"],
                    "negative_level": neg["level"], "negative_criterion_id": neg.get("criterion_id", ""),
                    "shared_set_id": neg.get("shared_set_id", ""),
                    "keyword_text": kw["keyword_text"], "keyword_match_type": kw["match_type"],
                    "keyword_criterion_id": kw.get("criterion_id", ""), "campaign_id": kw["campaign_id"],
                    "ad_group_id": kw.get("ad_group_id", ""),
                })
    return conflicts


def weak_performance(records: list[dict], thresholds: dict) -> list[dict]:
    min_clicks = thresholds["min_clicks_for_ratio"]
    min_spend = thresholds.get("min_spend_zero_conv")
    flags = []
    for r in records:
        if r.get("conversions") is None or r["conversions"] != 0:
            continue
        reasons = []
        if r["clicks"] >= min_clicks:
            reasons.append(f"0 conversions on {r['clicks']} clicks (≥ {min_clicks})")
        if min_spend is not None and r["cost"] >= Decimal(str(min_spend)):
            reasons.append(f"0 conversions on spend ≥ {min_spend}")
        if reasons:
            flags.append({"search_term": r["search_term"], "campaign_id": r["campaign_id"], "clicks": r["clicks"],
                          "cost": str(r["cost"]), "conversions": str(r["conversions"]), "flag": "; ".join(reasons)})
    return flags


def _negatives(args, log: RunLog) -> list[dict]:
    _, camp = records_from_snapshot(args.negatives, {"campaign_id", "keyword_text", "match_type"}, log, "negative_keywords")
    negs = [{**r, "level": "campaign", "scope_campaign_ids": [r["campaign_id"]]} for r in camp]
    if args.shared_negatives:
        if not args.campaign_shared_sets:
            raise StopAnalysis("--shared-negatives needs --campaign-shared-sets to know which campaigns they apply to")
        _, shared = records_from_snapshot(args.shared_negatives, {"shared_set_id", "keyword_text", "match_type"},
                                          log, "shared_negative_keywords")
        _, links = records_from_snapshot(args.campaign_shared_sets, {"campaign_id", "shared_set_id"},
                                         log, "campaign_shared_sets")
        linked: dict[str, list[str]] = {}
        for link in links:
            if link.get("shared_set_link_status", "ENABLED") == "ENABLED":
                linked.setdefault(link["shared_set_id"], []).append(link["campaign_id"])
        negs += [{**r, "level": "shared_set", "scope_campaign_ids": linked.get(r["shared_set_id"], [])} for r in shared]
    else:
        log.warn("shared negative keyword lists not supplied: conflict check covers campaign-level negatives only")
    return negs


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
    notes = "".join(f"<li>{escape(n)}</li>" for n in caveats + log.warnings)
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
<section class="card"><h2>Data caveats</h2><ul class="caveats">{notes or "<li>None detected.</li>"}</ul></section>"""
    footer = (f"Source: {escape(snap.path.name)} (fetched {escape(snap.fetched_at)}) · {len(rows)} rows · "
              f"{len(log.excluded)} excluded · currency {escape(currency)}")
    return page("Search-term review", f"Customer {snap.customer_id} · {snap.start} to {snap.end}",
                snap.synthetic, body, footer)


def run(args) -> Path:
    if not args.negatives:
        raise StopAnalysis("existing exclusions are required: pass --negatives (negative_keywords snapshot)")
    if not args.keywords:
        raise StopAnalysis("active keywords are required: pass --keywords (keywords snapshot)")
    log = RunLog()
    snap, terms = records_from_snapshot(args.search_terms, {"campaign_id", "search_term", "clicks", "cost"},
                                        log, "search_terms")
    grain = ("campaign_id", "ad_group_id", "search_term", "matched_keyword_text", "matched_keyword_match_type")
    check_unique(terms, grain)
    currency = check_single_currency(terms, args.expected_currency)
    caveats = partial_data_caveats(snap.end, account_timezone(terms, args.timezone), args.conversion_lag_days,
                                   parse_now(args.now))
    _, kw_records = records_from_snapshot(args.keywords, {"campaign_id", "keyword_text", "match_type"}, log, "keywords")
    keywords = [k for k in kw_records if k.get("negative") != "true"]
    ad_group_negs = [{**k, "level": "ad_group", "scope_campaign_ids": [k["campaign_id"]]}
                     for k in kw_records if k.get("negative") == "true"]
    negatives = _negatives(args, log) + ad_group_negs
    lists = json.loads(Path(args.brand_lists).read_text(encoding="utf-8"))
    if not any(lists.get(k) for k in ("marketplace", "stocked", "competitor")):
        log.warn("brand lists are empty: every term is classified generic_or_unknown")
    thresholds = json.loads((ROOT / "config" / "review_thresholds.json").read_text())

    per_term = []
    for key, t in group_by([{**r, "_k": f"{r['campaign_id']}\x1f{r['search_term']}"} for r in terms], "_k").items():
        cid, term = key.split("\x1f")
        per_term.append({"campaign_id": cid, "search_term": term, "clicks": t.clicks, "cost": t.cost,
                         "conversions": t.conversions, "conversion_value": t.conversion_value})
    weak = {(w["campaign_id"], w["search_term"]): w["flag"] for w in weak_performance(per_term, thresholds)}
    rows = [{
        "campaign_id": r["campaign_id"], "search_term": r["search_term"],
        "brand_class": classify_brand(r["search_term"], lists),
        "clicks": r["clicks"], "cost": str(r["cost"]),
        "conversions": None if r["conversions"] is None else str(r["conversions"]),
        "weak_performance": weak.get((r["campaign_id"], r["search_term"]), ""),
        "intent_review": "PENDING",
    } for r in sorted(per_term, key=lambda r: -r["cost"])]
    conflicts = find_conflicts(negatives, keywords)

    out = unique_dir(args.out, f"search-terms_{snap.customer_id}_{snap.start}_{snap.end}")
    (out / "candidates.json").write_text(json.dumps({
        "source": snap.path.name, "date_range": [str(snap.start), str(snap.end)], "synthetic": snap.synthetic,
        "currency": currency, "caveats": caveats, "coverage_note": COVERAGE_NOTE, "terms": rows, "conflicts": conflicts, "log": log.to_dict(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
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
    (out / "review.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "dashboard.html").write_text(render_search_dashboard(snap, currency, caveats, rows, conflicts, log),
                                        encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-terms", type=Path, required=True)
    ap.add_argument("--keywords", type=Path)
    ap.add_argument("--negatives", type=Path)
    ap.add_argument("--shared-negatives", type=Path)
    ap.add_argument("--campaign-shared-sets", type=Path)
    ap.add_argument("--expected-currency")
    ap.add_argument("--timezone", help="only if the snapshot lacks customer.time_zone")
    ap.add_argument("--conversion-lag-days", type=int)
    ap.add_argument("--now", help="ISO-8601 timestamp for partial-data checks (default: now; no offset = UTC)")
    ap.add_argument("--brand-lists", type=Path, default=ROOT / "config" / "brand_lists.json")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    args = ap.parse_args(argv)
    try:
        print(run(args))
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
