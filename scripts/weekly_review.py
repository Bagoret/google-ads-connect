#!/usr/bin/env python3
"""Weekly performance review from a campaign_daily MCP snapshot.

Usage:
  python3 scripts/weekly_review.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] \
      [--expected-currency EUR] [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Only pass --conversion-lag-days / --target-* values that are recorded (not UNKNOWN) in context/.
Exit code 2 = analysis stopped (reason printed); no output is written in that case.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.compare import Period, equivalence  # noqa: E402
from gads.findings import ReviewContext, generate_actions  # noqa: E402
from gads.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.metrics import Totals, aggregate, group_by  # noqa: E402
from gads.normalize import apply_field_map, detect_grain, extract_rows, flatten_row, load_field_map, load_snapshot  # noqa: E402
from gads.report import ReportData, render_report, write_outputs  # noqa: E402
from gads.validate import (account_timezone, check_date_coverage, check_single_currency, check_unique,  # noqa: E402
                           parse_now, partial_data_caveats)

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {"campaign_id", "date", "cost", "clicks"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _segment(periods: dict[str, list[dict]], meta: dict, field: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for label, recs in periods.items():
        for name, totals in group_by([{**r, "_seg": meta[r["campaign_id"]][field]} for r in recs], "_seg").items():
            out.setdefault(name, {})[label] = totals
    return out


@dataclass
class Review:
    """Everything a weekly review computes; shared by the report and the dashboard."""
    ctx: ReviewContext
    actions: list
    log: RunLog
    data: ReportData
    records: list[dict]
    periods: dict[str, list[dict]]


def build_review(args: argparse.Namespace) -> Review:
    log = RunLog()
    snap = load_snapshot(args.snapshot)
    if snap.query_name != "campaign_daily":
        raise StopAnalysis(f"weekly review needs a campaign_daily snapshot, got {snap.query_name}")
    rows = [flatten_row(r) for r in extract_rows(snap.payload, log)]
    records = apply_field_map(rows, load_field_map(), REQUIRED, log)
    if not records:
        raise StopAnalysis("snapshot contains no usable rows")
    grain = detect_grain(records)
    check_unique(records, tuple(grain))
    currency = check_single_currency(records, args.expected_currency)

    current = Period.parse(args.current)
    previous = Period.parse(args.previous) if args.previous else None
    for p in filter(None, [current, previous]):
        if snap.start is None or p.start < snap.start or p.end > snap.end:
            raise StopAnalysis(f"period {p} is outside the snapshot range {snap.start} to {snap.end}")
        check_date_coverage(records, p.start, p.end, log)
    equivalent, reasons = equivalence(current, previous) if previous else (False, [])

    tz = account_timezone(records, args.timezone)
    caveats = partial_data_caveats(current.end, tz, args.conversion_lag_days, parse_now(args.now))

    classification = _load_json(ROOT / "config" / "campaign_classification.json").get("campaigns", {})
    meta = _campaign_meta(records, classification)
    periods = {"current": _by_period(records, current)}
    if previous:
        periods["previous"] = _by_period(records, previous)

    account = {label: aggregate(recs) for label, recs in periods.items()}
    campaigns: dict[str, dict] = {}
    for label, recs in periods.items():
        for cid, totals in group_by(recs, "campaign_id").items():
            campaigns.setdefault(cid, {})[label] = totals
    # A campaign with previous-period rows but none now stopped serving (GAQL omits zero days):
    # keep it with zero current totals so its -100% shows up instead of vanishing.
    for cid, t in campaigns.items():
        if "current" not in t:
            prev = t["previous"]
            zero = Decimal(0)
            t["current"] = Totals(zero, 0, 0, None if prev.conversions is None else zero,
                                  None if prev.conversion_value is None else zero, 0)
            log.warn(f"campaign {cid} has rows in the previous period but none in the current period "
                     "(shown with zero current activity)")

    targets = {}
    if args.target_roas is not None:
        targets["roas"] = Decimal(args.target_roas)
    if args.target_cpa is not None:
        targets["cpa"] = Decimal(args.target_cpa)

    ctx = ReviewContext(
        current=current, previous=previous, equivalent=equivalent, account=account, campaigns=campaigns,
        campaign_meta=meta, thresholds=_load_json(ROOT / "config" / "review_thresholds.json"), targets=targets,
        caveats=caveats, source_label=snap.path.name, customer_id=snap.customer_id, currency=currency,
    )
    actions = generate_actions(ctx)
    parameters = {k: str(v) for k, v in vars(args).items()}
    data = ReportData(snapshot=snap, grain=grain, rows=len(records),
                      by_type=_segment(periods, meta, "campaign_type"),
                      by_brand=_segment(periods, meta, "brand_category"),
                      equivalence_reasons=reasons, parameters=parameters)
    return Review(ctx=ctx, actions=actions, log=log, data=data, records=records, periods=periods)


def run_review(args: argparse.Namespace) -> Path:
    r = build_review(args)
    report = render_report(r.ctx, r.actions, r.log, r.data)
    slug = f"weekly-review_{r.ctx.customer_id}_{r.ctx.current.start}_{r.ctx.current.end}"
    return write_outputs(args.out, slug, report, r.actions, r.log, r.data.parameters)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--current", required=True, help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--previous", help="YYYY-MM-DD:YYYY-MM-DD")
    ap.add_argument("--expected-currency")
    ap.add_argument("--timezone", help="only if the snapshot lacks customer.time_zone")
    ap.add_argument("--conversion-lag-days", type=int)
    ap.add_argument("--target-roas")
    ap.add_argument("--target-cpa")
    ap.add_argument("--now", help="ISO-8601 timestamp to evaluate partial data against (default: now)")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = run_review(args)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
