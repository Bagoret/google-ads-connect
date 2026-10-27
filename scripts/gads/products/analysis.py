"""Product (item) review computation from a product_daily snapshot, optionally joined to a business-supplied
margin/stock file. Revenue ROAS is never treated as profit. Rendering lives in gads.products.page."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gads.core.cli import load_json_file
from gads.core.contracts import QUERY_REQUIRED
from gads.core.logbook import RunLog, StopAnalysis
from gads.core.metrics import Totals, derive, fmt, group_by
from gads.core.normalize import Snapshot, records_from_snapshot
from gads.core.validate import (account_timezone, check_date_coverage, check_single_currency, check_unique,
                                parse_now, partial_data_caveats)

SOURCE_GRAIN = ("item_id", "campaign_id", "date")


def normalize_item_id(s: str) -> str:
    return str(s).strip().casefold()


def join_supplement(perf: dict[str, Totals], supplement: list[dict], log: RunLog
                    ) -> tuple[dict[str, dict], list[str], list[str]]:
    log.assume("item IDs normalised with strip + casefold on both sides before joining")
    by_id: dict[str, dict] = {}
    dupes = set()
    for item in supplement:
        key = normalize_item_id(item.get("item_id", ""))
        if not key:
            raise StopAnalysis("supplement row without item_id")
        if key in by_id:
            dupes.add(key)
        by_id[key] = item
    if dupes:
        raise StopAnalysis(f"duplicate item_id(s) in supplement would multiply revenue on join: {sorted(dupes)[:20]}")
    perf_n = {normalize_item_id(k): v for k, v in perf.items()}
    joined = {k: {"totals": t, "supplement": by_id.get(k)} for k, t in perf_n.items()}
    only_perf = sorted(k for k in perf_n if k not in by_id)
    only_supp = sorted(k for k in by_id if k not in perf_n)
    if only_perf:
        log.warn(f"{len(only_perf)} item(s) with performance but no supplement row")
    if only_supp:
        log.warn(f"{len(only_supp)} supplement item(s) with no performance in this period")
    return joined, only_perf, only_supp


def load_supplement(path: Path) -> tuple[list[dict], str | None]:
    data = load_json_file(path, "supplement")
    if not isinstance(data, dict):
        raise StopAnalysis(f'supplement {path} must be an object like {{"items": [...]}}')
    items = data.get("items", [])
    definition = data.get("margin_definition")
    if any(i.get("margin_rate") not in (None, "") for i in items) and not definition:
        raise StopAnalysis("supplement has margin_rate values but no margin_definition; state how margin is defined")
    for i in items:
        if i.get("margin_rate") not in (None, ""):
            try:
                rate = Decimal(str(i["margin_rate"]))
            except InvalidOperation:
                raise StopAnalysis(f"invalid margin_rate for {i.get('item_id')}: {i['margin_rate']!r}")
            if not (Decimal(0) <= rate <= Decimal(1)):
                raise StopAnalysis(f"margin_rate for {i.get('item_id')} must be between 0 and 1")
    return items, definition


@dataclass
class ProductReview:
    snap: Snapshot
    currency: str
    caveats: list[str]
    records: list[dict]
    joined: dict
    products: list[dict]
    definition: str | None
    only_perf: list[str]
    only_supp: list[str]
    log: RunLog


def analyse(args) -> ProductReview:
    """args: the product review's options (--products, --supplement, … as attributes)."""
    log = RunLog()
    snap, records = records_from_snapshot(args.products, QUERY_REQUIRED["product_daily"],
                                          log, "product_daily", dated=True)
    if not records:
        raise StopAnalysis("snapshot contains no usable rows")
    check_unique(records, SOURCE_GRAIN)
    currency = check_single_currency(records, args.expected_currency)
    caveats = partial_data_caveats(snap.end, account_timezone(records, args.timezone), args.conversion_lag_days,
                                   parse_now(args.now))
    check_date_coverage(records, snap.start, snap.end, log)
    for r in records:
        r["item_id"] = normalize_item_id(r["item_id"])
    titles = {r["item_id"]: (r.get("product_title", ""), r.get("product_brand", ""))
              for r in sorted(records, key=lambda r: r["date"])}  # latest row wins, as in the weekly review
    perf = group_by(records, "item_id")
    log.assume(f"grain aggregated from {' × '.join(SOURCE_GRAIN)} to item_id × period "
               "(all campaigns in this shopping_performance_view snapshot)")

    supplement, definition = (load_supplement(args.supplement) if args.supplement else ([], None))
    joined, only_perf, only_supp = join_supplement(perf, supplement, log) if supplement else (
        {k: {"totals": t, "supplement": None} for k, t in perf.items()}, [], [])

    products = []
    for item_id, j in sorted(joined.items(), key=lambda kv: -kv[1]["totals"].cost):
        t, s = j["totals"], j["supplement"] or {}
        d = derive(t)
        row = {"item_id": item_id, "title": titles[item_id][0], "brand": titles[item_id][1],
               "cost": str(fmt(t.cost, "ratio")), "clicks": t.clicks, "conversions": fmt(t.conversions, "conv"),
               "conversion_value": fmt(t.conversion_value, "ratio"), "revenue_roas": fmt(d["roas"], "ratio"),
               "cpa": fmt(d["cpa"], "ratio")}
        if definition and s.get("margin_rate") not in (None, "") and t.conversion_value is not None:
            margin = t.conversion_value * Decimal(str(s["margin_rate"]))
            row["margin_rate"] = str(s["margin_rate"])
            row["estimated_margin"] = fmt(margin, "ratio")
            row["margin_after_ad_cost"] = fmt(margin - t.cost, "ratio")
        if s.get("stock_status"):
            row["stock_status"] = s["stock_status"]
        products.append(row)
    return ProductReview(snap, currency, caveats, records, joined, products, definition, only_perf, only_supp, log)
