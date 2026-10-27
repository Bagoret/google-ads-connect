"""Markdown report and output files for the weekly review."""
from __future__ import annotations

import json
from pathlib import Path

from gads.core.compare import pct_change
from gads.weekly.analysis import ReportData
from gads.weekly.findings import ACTION_COLUMNS, Action, ReviewContext
from gads.core.logbook import RunLog
from gads.core.metrics import Totals, derive, fmt
from gads.core.files import unique_dir

CANNOT_TELL = [
    "Why a metric changed. Changes are observed; causes need change history, auction data, site and stock checks.",
    "Incrementality — whether conversions (especially marketplace-brand) would have happened without ads.",
    "Profit. Conversion value is revenue as defined in context/measurement.md, not margin.",
    "Every search query, or Performance Max channel/asset splits — those need separate queries.",
    "Anything that happened after the snapshot was fetched.",
]


def _delta(cur, prev) -> str:
    change = pct_change(cur, prev)
    return "N/A" if change is None else f"{change:+.1f}%"


def _metric_row(label: str, t: Totals, cur: str) -> str:
    d = derive(t)
    return (f"| {label} | {fmt(t.cost, 'money', cur)} | {fmt(t.impressions, 'count')} | {fmt(t.clicks, 'count')} | "
            f"{fmt(t.conversions, 'conv')} | {fmt(t.conversion_value, 'money', cur)} | {fmt(d['cpc'], 'money', cur)} | "
            f"{fmt(d['ctr'], 'pct')} | {fmt(d['cvr'], 'pct')} | {fmt(d['cpa'], 'money', cur)} | {fmt(d['roas'], 'ratio')} |")


def _delta_row(cur: Totals, prev: Totals) -> str:
    dc, dp = derive(cur), derive(prev)
    return (f"| Δ % | {_delta(cur.cost, prev.cost)} | {_delta(cur.impressions, prev.impressions)} | "
            f"{_delta(cur.clicks, prev.clicks)} | {_delta(cur.conversions, prev.conversions)} | "
            f"{_delta(cur.conversion_value, prev.conversion_value)} | {_delta(dc['cpc'], dp['cpc'])} | "
            f"{_delta(dc['ctr'], dp['ctr'])} | {_delta(dc['cvr'], dp['cvr'])} | {_delta(dc['cpa'], dp['cpa'])} | "
            f"{_delta(dc['roas'], dp['roas'])} |")


HEADER = ("| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|")


def _period_table(ctx: ReviewContext, totals: dict[str, Totals]) -> list[str]:
    lines = [HEADER, _metric_row(f"Current ({ctx.current})", totals["current"], ctx.currency)]
    if ctx.previous and "previous" in totals:
        lines.append(_metric_row(f"Previous ({ctx.previous})", totals["previous"], ctx.currency))
        if ctx.equivalent:
            lines.append(_delta_row(totals["current"], totals["previous"]))
    return lines


def _segment_section(ctx: ReviewContext, groups: dict[str, dict[str, Totals]]) -> list[str]:
    lines = []
    for name in sorted(groups):
        lines += [f"**{name}**", "", *_period_table(ctx, groups[name]), ""]
    return lines


def render_report(ctx: ReviewContext, actions: list[Action], log: RunLog, data: ReportData) -> str:
    snap, cur = data.snapshot, ctx.currency
    L: list[str] = [f"# Weekly review — customer {ctx.customer_id} — {ctx.current}", ""]
    if snap.synthetic:
        L += ["> **SYNTHETIC TEST DATA — NOT REAL.** This report was generated from a labelled test fixture.", ""]
    L += ["Statements are labelled **Observed** (from the named snapshot), **Hypothesis**, or **Recommendation**. "
          "All proposed actions require approval; nothing has been changed in any account.", ""]

    L += ["## Sources & grain", "",
          f"- Snapshot: `{snap.path.name}` (query `{snap.query_name}`, fetched {snap.fetched_at})",
          f"- Customer ID: {snap.customer_id} · Currency: {cur}",
          f"- Requested range in snapshot: {snap.start} to {snap.end}",
          f"- Grain: {' × '.join(data.grain)} · Rows used: {data.rows} · Rows excluded: {len(log.excluded)}",
          f"- Current period: {ctx.current}" + (f" · Previous period: {ctx.previous}" if ctx.previous else ""), ""]

    L += ["## Validation log", ""]
    for a in log.assumptions:
        L.append(f"- Assumption: {a}")
    for w in log.warnings:
        L.append(f"- Warning: {w}")
    for e in log.excluded:
        L.append(f"- Excluded row {e['index']}: {e['reason']}")
    if not (log.assumptions or log.warnings or log.excluded):
        L.append("- No assumptions, warnings, or excluded rows.")
    L.append("")

    L += ["## Comparison validity", ""]
    if not ctx.previous:
        L.append("No previous period requested; no comparison made.")
    elif ctx.equivalent:
        L.append(f"Equivalent periods ({ctx.current.days} days each, same weekday mix, no overlap). Deltas shown.")
    else:
        L.append(f"**Deltas suppressed** — periods are not equivalent: {'; '.join(data.equivalence_reasons)}. "
                 "Each period is shown separately; do not compare them directly.")
    L.append("")

    L += ["## Account totals", "", *_period_table(ctx, ctx.account), ""]
    L += ["## By campaign type", "", *_segment_section(ctx, data.by_type)]
    L += ["## By brand category", "",
          "Brand categories come from `config/campaign_classification.json`; `unclassified` means not yet mapped.", "",
          *_segment_section(ctx, data.by_brand)]

    L += ["## By campaign", "",
          "| Campaign ID | Name (latest) | Type | Brand | Cost | Clicks | Conv. | CPA | ROAS | Δ cost |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    ordered = sorted(ctx.campaigns.items(), key=lambda kv: -kv[1]["current"].cost)
    for cid, totals in ordered:
        meta, t = ctx.campaign_meta.get(cid, {}), totals["current"]
        d = derive(t)
        delta = _delta(t.cost, totals["previous"].cost) if ctx.equivalent and "previous" in totals else "N/A"
        L.append(f"| {cid} | {meta.get('name', '')} | {meta.get('campaign_type', '')} | "
                 f"{meta.get('brand_category', '')} | {fmt(t.cost, 'money', cur)} | {fmt(t.clicks, 'count')} | "
                 f"{fmt(t.conversions, 'conv')} | {fmt(d['cpa'], 'money', cur)} | {fmt(d['roas'], 'ratio')} | {delta} |")
    L.append("")

    L += ["## Observed material changes", ""]
    observed = [a for a in actions if a.finding.startswith(("Material change", "Conversions fell"))]
    for a in observed:
        L.append(f"- **Observed** [{a.entity_type} {a.entity_id}]: {a.finding}. Evidence: {a.supporting_metrics}")
    if not observed:
        L.append("- None above the configured thresholds" + ("" if ctx.equivalent and ctx.previous
                                                            else " (no valid comparison available)") + ".")
    L.append("")

    L += ["## Measurement caveats", ""]
    L += [f"- {c}" for c in ctx.caveats] or ["- None detected from timing; see context/measurement.md for setup limits."]
    if ctx.previous:
        L.append("- The previous period's conversions have had longer to be attributed than the current period's.")
    L.append("- Conversion definitions, attribution model and revenue basis: see context/measurement.md "
             "(UNKNOWN fields there limit interpretation).")
    L.append("")

    L += ["## Prioritised actions", "",
          "Full register: `actions.json` / `actions.md`. Every item is a **Recommendation** requiring approval.", "",
          "| # | Priority | Entity | Finding | Proposed action | Confidence |", "|---|---|---|---|---|---|"]
    for i, a in enumerate(actions, 1):
        L.append(f"| {i} | {a.priority} | {a.entity_type} {a.entity_id} | {a.finding} | {a.proposed_action} | {a.confidence} |")
    if not actions:
        L.append("| – | – | – | No rule fired | – | – |")
    L.append("")

    L += ["## Thresholds used", "",
          "Analysis sensitivity parameters from `config/review_thresholds.json` — defaults, not business-validated "
          "unless you have set them.", ""]
    L += [f"- `{k}`: {v}" for k, v in ctx.thresholds.items() if not k.startswith("_")]
    L += [f"- target `{k}`: {v} (supplied for this run)" for k, v in ctx.targets.items()] or ["- No targets supplied."]
    L.append("")

    L += ["## What this report cannot tell you", "", *[f"- {c}" for c in CANNOT_TELL], ""]
    return "\n".join(L)


def _actions_md(actions: list[Action]) -> str:
    head = "| " + " | ".join(ACTION_COLUMNS) + " |\n|" + "---|" * len(ACTION_COLUMNS)
    rows = ["| " + " | ".join(str(v).replace("|", "/") for v in a.as_dict().values()) + " |" for a in actions]
    return "\n".join(["# Action register", "", head, *rows, ""])


def write_outputs(out_root: Path, slug: str, report_md: str, actions: list[Action], log: RunLog,
                  parameters: dict | None = None) -> Path:
    out = unique_dir(out_root, slug)
    (out / "report.md").write_text(report_md, encoding="utf-8")
    (out / "actions.json").write_text(json.dumps([a.as_dict() for a in actions], indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    (out / "actions.md").write_text(_actions_md(actions), encoding="utf-8")
    (out / "run-log.json").write_text(json.dumps({"parameters": parameters or {}, "log": log.to_dict()},
                                                 indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return out
