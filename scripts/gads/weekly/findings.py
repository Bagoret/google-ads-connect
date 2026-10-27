"""Rule-based findings -> action register rows. Rules state observed facts; they never
assign causes. Every action requires approval."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from gads.core.compare import Period, pct_change
from gads.core.metrics import Totals, derive, fmt

ACTION_COLUMNS = ("priority", "entity_type", "entity_id", "finding", "supporting_metrics", "proposed_action",
                  "rationale", "confidence", "risk", "approval_required", "validation_plan")


@dataclass
class Action:
    priority: str
    entity_type: str
    entity_id: str
    finding: str
    supporting_metrics: str
    proposed_action: str
    rationale: str
    confidence: str
    risk: str
    approval_required: str
    validation_plan: str

    def as_dict(self) -> dict:
        data = asdict(self)
        return {k: data[k] for k in ACTION_COLUMNS}


@dataclass
class ReviewContext:
    current: Period
    previous: Period | None
    equivalent: bool
    account: dict[str, Totals]
    campaigns: dict[str, dict[str, Totals]]
    campaign_meta: dict[str, dict]
    thresholds: dict
    targets: dict
    caveats: list[str]
    source_label: str
    customer_id: str = ""
    currency: str = ""


def _summary(t: Totals, period: Period, cur: str) -> str:
    d = derive(t)
    return (f"{period}: cost={fmt(t.cost, 'money', cur)}, clicks={fmt(t.clicks, 'count')}, "
            f"conv={fmt(t.conversions, 'conv')}, value={fmt(t.conversion_value, 'money', cur)}, "
            f"CPA={fmt(d['cpa'], 'money', cur)}, ROAS={fmt(d['roas'], 'ratio')}, CVR={fmt(d['cvr'], 'pct')}")


def _evidence(ctx: ReviewContext, totals: dict[str, Totals]) -> str:
    parts = [f"current {_summary(totals['current'], ctx.current, ctx.currency)}"]
    if ctx.previous and "previous" in totals:
        parts.append(f"previous {_summary(totals['previous'], ctx.previous, ctx.currency)}")
    parts.append(f"source={ctx.source_label}")
    return "; ".join(parts)


def _confidence(ctx: ReviewContext, clicks: int) -> str:
    base = ctx.thresholds["min_clicks_for_ratio"]
    if clicks >= 3 * base:
        level = "high"
    elif clicks >= base:
        level = "medium"
    else:
        return "low"
    return "medium" if ctx.caveats and level == "high" else level


def _priority(default: str, confidence: str) -> str:
    return "P3" if confidence == "low" else default


def _action(ctx, priority, etype, eid, totals, finding, proposed, rationale, risk, validation, clicks) -> Action:
    conf = _confidence(ctx, clicks)
    return Action(_priority(priority, conf), etype, eid, finding, _evidence(ctx, totals), proposed,
                  rationale, conf, risk, "yes", validation)


def _rule_zero_conv(ctx: ReviewContext) -> list[Action]:
    limit = ctx.thresholds.get("min_spend_zero_conv")
    if limit is None:
        return []
    out = []
    min_cost = Decimal(str(limit))
    for cid, totals in ctx.campaigns.items():
        cur = totals["current"]
        if cur.conversions is not None and cur.conversions == 0 and cur.cost >= min_cost:
            out.append(_action(
                ctx, "P2", "campaign", cid, totals,
                f"Spent {fmt(cur.cost, 'money', ctx.currency)} with 0 conversions in {ctx.current}",
                "Review search terms, products, and landing pages for this campaign before any budget or bid change",
                f"Spend is above the configured review threshold ({limit}) with no recorded conversions.",
                "Conversions may arrive later (conversion delay); pausing could cut volume that converts with a lag.",
                "Re-check after the conversion delay window; compare with the prior equivalent period.",
                cur.clicks))
    return out


RATIO_METRICS = ("cpa", "roas", "cvr")


def _material_changes(ctx: ReviewContext, totals: dict[str, Totals]) -> list[str]:
    cur, prev = totals["current"], totals["previous"]
    limit = ctx.thresholds["material_pct_change"]
    changes = []
    cost_change = pct_change(cur.cost, prev.cost)
    if cost_change is not None and abs(cost_change) >= limit:
        changes.append(f"cost {cost_change:+.1f}%")
    min_clicks = ctx.thresholds["min_clicks_for_ratio"]
    if cur.clicks >= min_clicks and prev.clicks >= min_clicks:
        dc, dp = derive(cur), derive(prev)
        for m in RATIO_METRICS:
            change = pct_change(dc[m], dp[m])
            if change is not None and abs(change) >= limit:
                changes.append(f"{m.upper()} {change:+.1f}%")
    return changes


def _comparison_volume(totals: dict[str, Totals]) -> int:
    """Clicks backing a comparison: the smaller period, unless the entity stopped serving
    (no current rows), in which case the previous period's volume is the evidence."""
    cur, prev = totals["current"], totals["previous"]
    return prev.clicks if cur.rows == 0 else min(cur.clicks, prev.clicks)


def _rule_material(ctx: ReviewContext) -> list[Action]:
    if not (ctx.previous and ctx.equivalent) or ctx.thresholds.get("material_pct_change") is None:
        return []
    entities = [("account", ctx.customer_id or "account", ctx.account)]
    entities += [("campaign", cid, t) for cid, t in ctx.campaigns.items()]
    out = []
    for etype, eid, totals in entities:
        if "previous" not in totals:
            continue
        changes = _material_changes(ctx, totals)
        if changes:
            out.append(_action(
                ctx, "P2", etype, eid, totals,
                f"Material change vs {ctx.previous}: " + ", ".join(changes),
                "Investigate drivers (change history, budget limits, auction metrics, promotions, stock, "
                "landing pages) before changing bids or budgets",
                f"Change exceeds the configured materiality threshold ({ctx.thresholds['material_pct_change']}%). "
                "Cause not determined from this data.",
                "Reacting to noise or to conversions not yet attributed.",
                "Identify the driver from change history and the commercial calendar; re-run next week to see if it persists.",
                _comparison_volume(totals)))
    return out


def _rule_targets(ctx: ReviewContext) -> list[Action]:
    if not ctx.targets:
        return []
    out = []
    min_clicks = ctx.thresholds["min_clicks_for_ratio"]
    target_roas = Decimal(str(ctx.targets["roas"])) if "roas" in ctx.targets else None
    target_cpa = Decimal(str(ctx.targets["cpa"])) if "cpa" in ctx.targets else None
    for cid, totals in ctx.campaigns.items():
        cur = totals["current"]
        if cur.clicks < min_clicks:
            continue
        d = derive(cur)
        if target_roas is not None and d["roas"] is not None and d["roas"] < target_roas:
            out.append(_action(
                ctx, "P2", "campaign", cid, totals,
                f"ROAS {fmt(d['roas'], 'ratio')} is below supplied target ROAS {ctx.targets['roas']}",
                "Investigate efficiency drivers; consider target/bid adjustments only after review",
                "Target supplied for this review (from context/business.md).",
                "The target may not apply to this campaign type or brand category.",
                "Re-check ROAS after the conversion delay window over an equivalent period.",
                cur.clicks))
        if target_cpa is not None and d["cpa"] is not None and d["cpa"] > target_cpa:
            out.append(_action(
                ctx, "P2", "campaign", cid, totals,
                f"CPA {fmt(d['cpa'], 'money', ctx.currency)} is above supplied target CPA {ctx.targets['cpa']}",
                "Investigate efficiency drivers; consider target/bid adjustments only after review",
                "Target supplied for this review (from context/business.md).",
                "The target may not apply to this campaign type or brand category.",
                "Re-check CPA after the conversion delay window over an equivalent period.",
                cur.clicks))
    return out


def generate_actions(ctx: ReviewContext) -> list[Action]:
    actions = _rule_zero_conv(ctx) + _rule_material(ctx) + _rule_targets(ctx)

    def cost_of(a: Action) -> Decimal:
        if a.entity_type == "campaign" and a.entity_id in ctx.campaigns:
            return ctx.campaigns[a.entity_id]["current"].cost
        return ctx.account["current"].cost

    return sorted(actions, key=lambda a: (a.priority, -cost_of(a)))
