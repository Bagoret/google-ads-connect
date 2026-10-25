"""Validation checks that stop or caveat an analysis instead of letting bad data through."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .logbook import RunLog, StopAnalysis


def check_unique(records: list[dict], key: tuple[str, ...]) -> None:
    counts = Counter(tuple(r.get(k) for k in key) for r in records)
    dupes = [k for k, n in counts.items() if n > 1]
    if dupes:
        shown = "; ".join(str(dict(zip(key, map(str, d)))) for d in dupes[:20])
        raise StopAnalysis(f"{len(dupes)} duplicate key(s) on grain {key}: {shown}")


def check_single_currency(records: list[dict], expected: str | None) -> str:
    found = sorted({r["currency"] for r in records if r.get("currency")})
    if len(found) > 1:
        raise StopAnalysis(f"mixed currencies in one dataset: {found}")
    if found and expected and found[0] != expected:
        raise StopAnalysis(f"data currency {found[0]} does not match expected {expected}")
    if not found and not expected:
        raise StopAnalysis("currency unknown: not in data and no --expected-currency given")
    return found[0] if found else expected


def check_date_coverage(records: list[dict], start: date, end: date, log: RunLog) -> list[date]:
    seen = {r["date"] for r in records if r.get("date")}
    missing = []
    day = start
    while day <= end:
        if day not in seen:
            missing.append(day)
        day += timedelta(days=1)
    if missing:
        log.warn(f"{len(missing)} date(s) with no rows ({', '.join(map(str, missing[:10]))}): "
                 "zero activity or incomplete data — cannot tell which from the response")
    return missing


def partial_data_caveats(end: date, account_tz: str, lag_days: int | None, now_utc: datetime) -> list[str]:
    try:
        today = now_utc.astimezone(ZoneInfo(account_tz)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise StopAnalysis(f"unknown account timezone {account_tz!r}")
    caveats = []
    if end >= today:
        caveats.append(f"period end {end} is today or later in the account timezone ({account_tz}): "
                       "that day's data is partial")
    if lag_days is None:
        caveats.append("conversion delay unknown (context/measurement.md): recent conversions and "
                       "conversion value may still increase")
    else:
        age = (today - end).days
        if age < lag_days:
            caveats.append(f"period ended {max(age, 0)} day(s) ago, within the {lag_days}-day conversion delay: "
                           "conversions and conversion value are likely understated")
    return caveats
