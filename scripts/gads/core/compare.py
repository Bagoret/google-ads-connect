"""Comparison periods and whether two periods can be compared fairly."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from gads.core.logbook import StopAnalysis


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @classmethod
    def parse(cls, text: str) -> "Period":
        try:
            a, b = text.split(":")
            period = cls(date.fromisoformat(a), date.fromisoformat(b))
        except ValueError:
            raise StopAnalysis(f"invalid period {text!r}; expected YYYY-MM-DD:YYYY-MM-DD")
        if period.start > period.end:
            raise StopAnalysis(f"period {text} starts after it ends")
        return period

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def weekday_counts(self) -> tuple[int, ...]:
        counts = [0] * 7
        for i in range(self.days):
            counts[(self.start + timedelta(days=i)).weekday()] += 1
        return tuple(counts)

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def __str__(self) -> str:
        return f"{self.start} to {self.end}"


def equivalence(cur: Period, prev: Period) -> tuple[bool, list[str]]:
    reasons = []
    if cur.days != prev.days:
        reasons.append(f"different length ({cur.days} vs {prev.days} days)")
    elif cur.weekday_counts() != prev.weekday_counts():
        reasons.append("different weekday mix")
    if cur.start <= prev.end and prev.start <= cur.end:
        reasons.append("periods overlap")
    return (not reasons, reasons)


def pct_change(cur: Decimal | None, prev: Decimal | None) -> Decimal | None:
    if cur is None or prev is None or prev == 0:
        return None
    return (Decimal(cur) - Decimal(prev)) / Decimal(prev) * 100
