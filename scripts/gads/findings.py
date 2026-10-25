"""Rule-based findings -> action register rows. Rules state observed facts; they never
assign causes. Every action requires approval."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from .compare import Period, pct_change
from .metrics import Totals, derive, fmt

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
        return {k: asdict(self)[k] for k in ACTION_COLUMNS}


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


def _rule_tracking(ctx: ReviewContext) -> list[Action]:
    if not (ctx.previous and ctx.equivalent and "previous" in ctx.account):
        return []
    cur, prev = ctx.account["current"], ctx.account["previous"]
    if not prev.conversions or cur.conversions is None:
        return []
    drop = -pct_change(cur.conversions, prev.conversions)
    click_change = pct_change(Decimal(cur.clicks), Decimal(prev.clicks))
    if drop < ctx.thresholds["tracking_drop_pct"] or click_change is None:
        return []
    if abs(click_change) > ctx.thresholds["tracking_click_stability_pct"]:
        return []
    act = _action(
        ctx, "P1", "account", ctx.customer_id or "account", ctx.account,
        f"Conversions fell {drop:.1f}% while clicks changed {click_change:+.1f}%",
        "Verify conversion tracking before any optimisation",
        "A large conversion drop with stable traffic is consistent with a measurement problem; "
        "it is also consistent with a real demand or site change — the data cannot tell which.",
        "Optimising on broken tracking would misdirect spend; smart bidding may already be reacting.",
        "Compare Google Ads conversions with back-end orders for the same days; check conversion action "
        "status and recent tag/site changes; re-run this review after the check.",
        cur.clicks)
    act.priority = "P1"
    return [act]


def _rule_zero_conv(ctx: ReviewContext) -> list[Action]:
    limit = ctx.thresholds.get("min_spend_zero_conv")
    if limit is None:
        return []
    out = []
    for cid, totals in ctx.campaigns.items():
        cur = totals["current"]
        if cur.conversions is not None and cur.conversions == 0 and cur.cost >= Decimal(str(limit)):
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


def _rule_material(ctx: ReviewContext) -> list[Action]:
    if not (ctx.previous and ctx.equivalent):
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
                min(totals["current"].clicks, totals["previous"].clicks)))
    return out


def _rule_targets(ctx: ReviewContext) -> list[Action]:
    if not ctx.targets:
        return []
    out = []
    min_clicks = ctx.thresholds["min_clicks_for_ratio"]
    for cid, totals in ctx.campaigns.items():
        cur = totals["current"]
        if cur.clicks < min_clicks:
            continue
        d = derive(cur)
        if "roas" in ctx.targets and d["roas"] is not None and d["roas"] < Decimal(str(ctx.targets["roas"])):
            out.append(_action(
                ctx, "P2", "campaign", cid, totals,
                f"ROAS {fmt(d['roas'], 'ratio')} is below supplied target ROAS {ctx.targets['roas']}",
                "Investigate efficiency drivers; consider target/bid adjustments only after review",
                "Target supplied for this review (from context/business.md).",
                "The target may not apply to this campaign type or brand category.",
                "Re-check ROAS after the conversion delay window over an equivalent period.",
                cur.clicks))
        if "cpa" in ctx.targets and d["cpa"] is not None and d["cpa"] > Decimal(str(ctx.targets["cpa"])):
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
    actions = _rule_tracking(ctx) + _rule_zero_conv(ctx) + _rule_material(ctx) + _rule_targets(ctx)

    def cost_of(a: Action) -> Decimal:
        if a.entity_type == "campaign" and a.entity_id in ctx.campaigns:
            return ctx.campaigns[a.entity_id]["current"].cost
        return ctx.account["current"].cost

    return sorted(actions, key=lambda a: (a.priority, -cost_of(a)))
