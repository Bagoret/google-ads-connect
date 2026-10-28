"""The first-connection report (Markdown) and summary (JSON). Field names, counts and statuses only: no campaign
names, search terms, products or figures, so it can be shared to get help."""
from __future__ import annotations

from dataclasses import asdict

from gads.onboarding.first_connect import FirstConnect

STATUS_ICON = {"PASS": "✓", "EMPTY": "○", "FAIL": "✕", "READY": "✓", "NO DATA": "○", "BLOCKED": "✕"}
FEATURE_MEANING = {
    "READY": "can run on this account",
    "NO DATA": "data shape is fine, but the account returned no rows for this period (e.g. no campaigns of that type)",
    "BLOCKED": "a query it needs failed; see below",
}


def summary(fc: FirstConnect) -> dict:
    return {
        "customer_id": fc.customer_id,
        "period": [str(fc.period[0]), str(fc.period[1])],
        "period_note": fc.period_note,
        "features": fc.features,
        "queries": [asdict(q) for q in fc.queries],
        "contains_account_values": False,
    }


def render_markdown(fc: FirstConnect, generated_at: str) -> str:
    L = [f"# First-connection check — customer {fc.customer_id}", "",
         f"Generated {generated_at} · dated queries fetched for {fc.period[0]} to {fc.period[1]}."
         + (f" {fc.period_note}" if fc.period_note else ""), "",
         "> Contains field names, row counts and statuses only (no campaign names, search terms, products or "
         "figures), so it is safe to share when asking for help.", "",
         "## Verdict", ""]
    blocked = [f for f in fc.features if f["status"] == "BLOCKED"]
    L.append("**Every query passed the contract gate.**" if not fc.failed else
             f"**{sum(q.status == 'FAIL' for q in fc.queries)} query(ies) failed**, blocking: "
             + ", ".join(f["feature"] for f in blocked) + ". Fix those first; the other features can already run.")
    L += ["", "| Feature | Status | Meaning | Needs |", "|---|---|---|---|"]
    for f in fc.features:
        notes = f" ({'; '.join(f['notes'])})" if f["notes"] else ""
        L.append(f"| {f['feature']} | {STATUS_ICON[f['status']]} {f['status']} | {FEATURE_MEANING[f['status']]}{notes} | "
                 f"{', '.join(f['needs'])} |")
    L += ["", "## Queries", "", "| Query | Status | Rows | Dates returned | Unmapped fields | Snapshot |",
          "|---|---|---|---|---|---|"]
    for q in fc.queries:
        dates = f"{q.date_range[0]} to {q.date_range[1]}" if q.date_range else "–"
        L.append(f"| {q.query} | {STATUS_ICON[q.status]} {q.status} | {q.rows} | {dates} | "
                 f"{', '.join(q.unmapped) or '–'} | {q.snapshot or '–'} |")
    problems = [q for q in fc.queries if q.status != "PASS"]
    if problems:
        L += ["", "## Details", ""]
        for q in problems:
            L.append(f"- **{q.query}** ({q.status}): {q.detail}")
    L += ["", "## Next steps", ""]
    quiet = any(q.status == "EMPTY" and q.date_range is None and "--end" in q.detail for q in fc.queries)
    if fc.failed:
        L += ["- Fix the failed queries (a common cause is API access: the Cloud project needs Explorer access or "
              "higher for real accounts), then re-run `python3 scripts/first_connect.py`.",
              "- Share this report (it holds no account data) if you need help with a failure."]
    else:
        period = "a period when the campaigns were running" if quiet else "last week"
        L += [f"- In Claude Code, say **\"run onboarding\"**, then **\"weekly review for {period}\"**."]
    if quiet:
        L.append("- Dated queries returned no rows for this period. If your campaigns are paused, find the last day "
                 f"with impressions: `python3 scripts/last_active.py --customer-id {fc.customer_id}`, then re-run "
                 f"`python3 scripts/first_connect.py --customer-id {fc.customer_id} --end <that day> --days 30`.")
    if any(q.unmapped for q in fc.queries):
        L.append("- Unmapped fields are returned by Google but not used yet (not an error); add them to "
                 "`config/field_map.json` only when a feature needs them.")
    return "\n".join(L) + "\n"
