"""Validation checks that stop or caveat an analysis instead of letting bad data through."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gads.core.logbook import RunLog, StopAnalysis


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


# Google Ads conversion windows are at most 90 days (support.google.com/google-ads/answer/3123169): a period that
# ended longer ago than that can no longer gain conversions, whatever the account's settings.
MAX_CONVERSION_WINDOW_DAYS = 90
CONVERSION_DELAY = "conversion delay"  # every delay caveat contains this phrase (the dashboard looks for it)


def partial_data_caveats(end: date, account_tz: str, lag_days: int | None, now_utc: datetime) -> list[str]:
    try:
        today = now_utc.astimezone(ZoneInfo(account_tz)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise StopAnalysis(f"unknown account timezone {account_tz!r}")
    caveats = []
    if end >= today:
        caveats.append(f"period end {end} is today or later in the account timezone ({account_tz}): "
                       "that day's data is partial")
    age = (today - end).days
    if age > MAX_CONVERSION_WINDOW_DAYS:
        return caveats
    if lag_days is None:
        caveats.append(f"{CONVERSION_DELAY} unknown (context/measurement.md): the period ended {max(age, 0)} day(s) "
                       f"ago, within Google's maximum {MAX_CONVERSION_WINDOW_DAYS}-day conversion window, so "
                       "conversions and conversion value may still increase")
    else:
        if age < lag_days:
            caveats.append(f"period ended {max(age, 0)} day(s) ago, within the {lag_days}-day conversion delay: "
                           "conversions and conversion value are likely understated")
    return caveats


def account_timezone(records: list[dict], fallback: str | None) -> str:
    zones = sorted({r["time_zone"] for r in records if r.get("time_zone")}) or ([fallback] if fallback else [])
    if len(zones) != 1:
        raise StopAnalysis(f"account timezone undetermined ({zones}); pass --timezone from context/business.md")
    return zones[0]


def parse_now(text: str | None) -> datetime:
    """--now value; an ISO timestamp without an offset is taken as UTC, never machine-local time."""
    if not text:
        from datetime import timezone
        return datetime.now(timezone.utc)
    now = datetime.fromisoformat(text)
    if now.tzinfo is None:
        from datetime import timezone
        now = now.replace(tzinfo=timezone.utc)
    return now
