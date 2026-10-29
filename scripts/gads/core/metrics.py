"""Totals and derived ratios. Undefined ratios are None (rendered "N/A"), never 0."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Literal

ZERO = Decimal(0)


@dataclass
class Totals:
    cost: Decimal
    clicks: int
    impressions: int
    conversions: Decimal | None
    conversion_value: Decimal | None
    rows: int
    # Every conversion action, including secondary ones (page views, add to cart ...); None if not fetched.
    all_conversions: Decimal | None = None
    all_conversion_value: Decimal | None = None


def aggregate(records: Iterable[dict]) -> Totals:
    records = list(records)
    has_conv = bool(records) and all(r.get("conversions") is not None for r in records)
    has_value = bool(records) and all(r.get("conversion_value") is not None for r in records)

    def total_if_present(key: str) -> Decimal | None:
        if not records or any(r.get(key) is None for r in records):
            return None
        return sum((r[key] for r in records), ZERO)
    return Totals(
        cost=sum((r.get("cost") or ZERO for r in records), ZERO),
        clicks=sum(r.get("clicks") or 0 for r in records),
        impressions=sum(r.get("impressions") or 0 for r in records),
        conversions=sum((r["conversions"] for r in records), ZERO) if has_conv else None,
        conversion_value=sum((r["conversion_value"] for r in records), ZERO) if has_value else None,
        rows=len(records),
        all_conversions=total_if_present("all_conversions"),
        all_conversion_value=total_if_present("all_conversion_value"),
    )


def group_by(records: Iterable[dict], key: str) -> dict[str, Totals]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(str(r.get(key)), []).append(r)
    return {k: aggregate(v) for k, v in groups.items()}


def _div(num, den) -> Decimal | None:
    if num is None or den is None or den == 0:
        return None
    return Decimal(num) / Decimal(den)


def derive(t: Totals) -> dict[str, Decimal | None]:
    return {
        "cpc": _div(t.cost, t.clicks),
        "ctr": _div(t.clicks, t.impressions),
        "cvr": _div(t.conversions, t.clicks),
        "cpa": _div(t.cost, t.conversions),
        "roas": _div(t.conversion_value, t.cost),
        "value_per_conversion": _div(t.conversion_value, t.conversions),
    }


def _q(value: Decimal, places: str = "0.01") -> Decimal:
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def fmt(value: Decimal | int | None, kind: Literal["money", "ratio", "pct", "count", "conv"], currency: str = "") -> str:
    if value is None:
        return "N/A"
    if kind == "money":
        return f"{_q(value)} {currency}".strip()
    if kind == "pct":
        return f"{_q(Decimal(value) * 100)}%"
    if kind == "count":
        return f"{int(value):,}"
    if kind in ("ratio", "conv"):
        return str(_q(value))
    raise ValueError(kind)
