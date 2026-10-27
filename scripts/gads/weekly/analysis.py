"""Weekly review computation: load a campaign_daily snapshot, validate it, aggregate by period, campaign and
segment, and generate rule-based findings. No rendering here; see gads.weekly.report and dashboard pages."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gads.core.thresholds import load_thresholds
from gads.weekly.findings import ReviewContext, generate_actions
from gads.core.cli import add_common_args, load_json_file
from gads.core.compare import Period, equivalence
from gads.core.logbook import RunLog, StopAnalysis
from gads.core.metrics import Totals, aggregate, group_by
from gads.core.normalize import Snapshot, detect_grain, records_from_snapshot
from gads.core.files import ROOT
from gads.core.validate import (account_timezone, check_date_coverage, check_single_currency, check_unique,
                                parse_now, partial_data_caveats)

REQUIRED = {"campaign_id", "date", "cost", "clicks"}


def add_weekly_args(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The weekly review's inputs as command-line flags (shared by weekly_review.py and dashboard.py)."""
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--current", required=True, help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--previous", help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--target-roas")
    ap.add_argument("--target-cpa")
    return add_common_args(ap)


@dataclass
class ReportData:
    """Everything the renderer needs beyond the findings context."""
    snapshot: Snapshot
    grain: list[str]
    rows: int
    by_type: dict[str, dict[str, Totals]]
    by_brand: dict[str, dict[str, Totals]]
    equivalence_reasons: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)


def _by_period(records: list[dict], period: Period) -> list[dict]:
    return [r for r in records if period.contains(r["date"])]


def _campaign_meta(records: list[dict], classification: dict) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for r in sorted(records, key=lambda r: r["date"]):  # latest row wins for the name
        cid = r["campaign_id"]
        mapped = classification.get(cid, {})
        meta[cid] = {
            "name": r.get("campaign_name", ""),
            "campaign_type": mapped.get("campaign_type") or r.get("channel_type") or "unclassified",
            "brand_category": mapped.get("brand_category") or "unclassified",
        }
    return meta


def _by_label(periods: dict[str, list[dict]], key) -> dict[str, dict]:
    """Totals per group and period label; a group with previous rows but none now (it stopped serving, and
    GAQL omits zero days) gets zero current totals so its -100% shows instead of vanishing."""
    out: dict[str, dict] = {}
    for label, recs in periods.items():
        for name, totals in group_by([{**r, "_g": key(r)} for r in recs], "_g").items():
            out.setdefault(name, {})[label] = totals
    for t in out.values():
        if "current" not in t:
            prev = t["previous"]
            zero = Decimal(0)
            t["current"] = Totals(zero, 0, 0, None if prev.conversions is None else zero,
                                  None if prev.conversion_value is None else zero, 0)
    return out


def _target(raw: str | None, name: str) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise StopAnalysis(f"--target-{name} must be a number, got {raw!r}")
    if not value.is_finite() or value <= 0:
        raise StopAnalysis(f"--target-{name} must be a positive number, got {raw!r}")
    return value


@dataclass
class Review:
    """Everything a weekly review computes; shared by the report and the dashboard."""
    ctx: ReviewContext
    actions: list
    log: RunLog
    data: ReportData
    records: list[dict]
    periods: dict[str, list[dict]]


def build_review(args) -> Review:
    """args: the weekly review's command-line options (an argparse.Namespace or any object with them)."""
    log = RunLog()
    snap, records = records_from_snapshot(args.snapshot, REQUIRED, log, "campaign_daily")
    if not records:
        raise StopAnalysis("snapshot contains no usable rows")
    grain = detect_grain(records)
    check_unique(records, tuple(grain))
    currency = check_single_currency(records, args.expected_currency)

    current = Period.parse(args.current)
    previous = Period.parse(args.previous) if args.previous else None
    for p in filter(None, [current, previous]):
        if snap.start is None or snap.end is None or p.start < snap.start or p.end > snap.end:
            raise StopAnalysis(f"period {p} is outside the snapshot range {snap.start} to {snap.end}")
        check_date_coverage(records, p.start, p.end, log)
    equivalent, reasons = equivalence(current, previous) if previous else (False, [])

    tz = account_timezone(records, args.timezone)
    caveats = partial_data_caveats(current.end, tz, args.conversion_lag_days, parse_now(args.now))

    classification = load_json_file(ROOT / "config" / "campaign_classification.json",
                                    "campaign classification").get("campaigns", {})
    meta = _campaign_meta(records, classification)
    periods = {"current": _by_period(records, current)}
    if previous:
        periods["previous"] = _by_period(records, previous)

    account = {label: aggregate(recs) for label, recs in periods.items()}
    campaigns = _by_label(periods, lambda r: r["campaign_id"])
    for cid, t in campaigns.items():
        if t["current"].rows == 0:
            log.warn(f"campaign {cid} has rows in the previous period but none in the current period "
                     "(shown with zero current activity)")

    targets = {k: v for k, v in (("roas", _target(args.target_roas, "roas")),
                                 ("cpa", _target(args.target_cpa, "cpa"))) if v is not None}
    thresholds = load_thresholds()

    ctx = ReviewContext(
        current=current, previous=previous, equivalent=equivalent, account=account, campaigns=campaigns,
        campaign_meta=meta, thresholds=thresholds, targets=targets,
        caveats=caveats, source_label=snap.path.name, customer_id=snap.customer_id, currency=currency,
    )
    actions = generate_actions(ctx)
    parameters = {k: str(v) for k, v in vars(args).items()}
    data = ReportData(snapshot=snap, grain=grain, rows=len(records),
                      by_type=_by_label(periods, lambda r: meta[r["campaign_id"]]["campaign_type"]),
                      by_brand=_by_label(periods, lambda r: meta[r["campaign_id"]]["brand_category"]),
                      equivalence_reasons=reasons, parameters=parameters)
    return Review(ctx=ctx, actions=actions, log=log, data=data, records=records, periods=periods)


