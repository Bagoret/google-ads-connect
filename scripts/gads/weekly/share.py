"""Impression share per campaign for the current period, from the campaign_share query. Google computes shares
over the whole period (they cannot be summed from daily rows), so the snapshot must cover exactly that period."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from gads.core.compare import Period
from gads.core.contracts import QUERY_REQUIRED
from gads.core.logbook import RunLog
from gads.core.metrics import fmt
from gads.core.normalize import records_from_snapshot
from gads.core.validate import check_same_scope, check_unique

# (field, short label, meaning)
SHARE_FIELDS = (
    ("impression_share", "Impr. share", "share of eligible search impressions received"),
    ("budget_lost_impression_share", "Lost: budget", "eligible impressions lost because the budget ran out"),
    ("rank_lost_impression_share", "Lost: rank", "eligible impressions lost to ad rank (bid, quality)"),
    ("top_impression_share", "Top", "share shown above the organic results"),
    ("absolute_top_impression_share", "Abs. top", "share shown as the very first ad"),
)
# The API returns a share below 10% as 0.0999 and a lost share above 90% as 0.9001, not the exact value.
BELOW_10 = Decimal("0.0999")
ABOVE_90 = Decimal("0.9001")


def load_shares(path: Path, customer_id: str, period: Period, log: RunLog) -> dict[str, dict[str, Decimal | None]]:
    snap, records = records_from_snapshot(path, QUERY_REQUIRED["campaign_share"], log, "campaign_share", dated=True)
    check_same_scope(snap, customer_id, period.start, period.end, f"share snapshot {Path(path).name}")
    check_unique(records, ("campaign_id",))
    return {r["campaign_id"]: {f: r.get(f) for f, _, _ in SHARE_FIELDS} for r in records}


def fmt_share(value: Decimal | None) -> str:
    if value == BELOW_10:
        return "< 10%"
    if value == ABOVE_90:
        return "> 90%"
    return fmt(value, "pct")
