"""Measurement check: which conversion actions make up "Conversions" in the current period, and which of them
probably should not (a secondary action counted through a goal override, or page views counted as conversions).
CPA, ROAS and Smart Bidding all rest on that number, so this is checked before reading them."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from gads.core.contracts import QUERY_REQUIRED
from gads.core.logbook import RunLog, StopAnalysis
from gads.core.metrics import ZERO, fmt
from gads.core.normalize import records_from_snapshot
from gads.core.validate import check_same_scope, check_unique
from gads.weekly.findings import Action, ReviewContext

NOT_OUTCOMES = {"PAGE_VIEW"}   # categories that are not a business outcome for an e-commerce account
TOLERANCE = Decimal("0.01")    # fractional (data-driven) conversions may not add up to the last digit


@dataclass
class ActionRow:
    action_id: str
    name: str
    category: str
    conversions: Decimal
    conversion_value: Decimal | None
    all_conversions: Decimal | None
    counted_by_setting: bool | None   # include_in_conversions_metric; None without the settings snapshot


@dataclass
class Measurement:
    rows: list[ActionRow]
    source: str
    settings_source: str | None
    total: Decimal                    # sum of conversions over all actions
    account_total: Decimal | None     # conversions in the campaign snapshot for the same period

    @property
    def reconciles(self) -> bool | None:
        if self.account_total is None:
            return None
        return abs(self.total - self.account_total) <= TOLERANCE


def _action_id(resource: str) -> str:
    tail = str(resource).rsplit("/", 1)[-1]
    if not tail.isdigit():
        raise StopAnalysis(f"unexpected conversion action reference {resource!r}")
    return tail


def _settings(path: Path, customer_id: str, log: RunLog) -> dict[str, bool]:
    snap, records = records_from_snapshot(path, QUERY_REQUIRED["conversion_actions"], log, "conversion_actions")
    check_same_scope(snap, customer_id, None, None, f"conversion settings snapshot {Path(path).name}")
    return {r["conversion_action_id"]: str(r.get("include_in_conversions")).lower() == "true"
            for r in records if r.get("include_in_conversions") is not None}


def build_measurement(path: Path, settings_path: Path | None, ctx: ReviewContext, log: RunLog) -> Measurement:
    snap, records = records_from_snapshot(path, QUERY_REQUIRED["conversions_by_action"], log,
                                          "conversions_by_action", dated=True)
    check_same_scope(snap, ctx.customer_id, ctx.current.start, ctx.current.end,
                     f"conversions snapshot {Path(path).name}")
    check_unique(records, ("conversion_action_resource",))
    counted = _settings(settings_path, ctx.customer_id, log) if settings_path else {}
    rows = []
    for r in records:
        aid = _action_id(r["conversion_action_resource"])
        rows.append(ActionRow(aid, r.get("conversion_action_name") or "", r.get("conversion_category") or "",
                              r["conversions"], r.get("conversion_value"), r.get("all_conversions"),
                              counted.get(aid) if settings_path else None))
    rows.sort(key=lambda a: (-a.conversions, -(a.all_conversions or ZERO)))
    m = Measurement(rows, Path(path).name, Path(settings_path).name if settings_path else None,
                    sum((a.conversions for a in rows), ZERO), ctx.account["current"].conversions)
    if m.reconciles is False:
        log.warn(f"conversions by action ({m.total}) do not add up to the campaign snapshot's conversions "
                 f"({m.account_total}) for {ctx.current}: the two snapshots may come from different fetches")
    return m


def measurement_actions(m: Measurement, ctx: ReviewContext) -> list[Action]:
    out = []
    for a in m.rows:
        secondary = a.counted_by_setting is False
        not_outcome = a.category in NOT_OUTCOMES
        if a.conversions <= 0 or not (secondary or not_outcome):
            continue
        why = ("its include-in-conversions setting is off (secondary), so it reaches Conversions through a goal "
               "override, for example a campaign-level goal; which one is not determined from this data."
               if secondary else
               f"{a.category} is not a business outcome for an e-commerce account.")
        out.append(Action(
            "P1" if secondary else "P2", "conversion_action", a.action_id,
            f"{a.name} ({a.category}) {'is set as secondary but ' if secondary else ''}counted "
            f"{fmt(a.conversions, 'conv')} of {fmt(m.total, 'conv')} conversions in {ctx.current}",
            f"{m.source}{f' + {m.settings_source}' if m.settings_source else ''}; {ctx.current}; "
            f"conversions {fmt(a.conversions, 'conv')}, value {fmt(a.conversion_value, 'money', ctx.currency)}, "
            f"all conversions {fmt(a.all_conversions, 'conv')}",
            "Check which conversion goals each campaign uses (account default goals and campaign-level goals) and "
            "decide whether this action should count; until then read CPA and ROAS as including it",
            "Observed in the conversions-by-action breakdown: " + why,
            "high",
            "CPA, ROAS and Smart Bidding use these conversions; changing goals changes what bidding optimises for.",
            "yes",
            "Re-run the measurement check after any goal change: Conversions should contain only intended actions."))
    return out
