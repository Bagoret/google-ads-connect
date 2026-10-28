"""Finding the last day an account was active (had impressions), so reviews of a paused account can default to a
period with data instead of returning no rows. One read-only query (queries/account_activity.gaql): one row per
day with impressions, at account level."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from gads.connect.snapshot import run_snapshot
from gads.core.files import ROOT
from gads.core.logbook import RunLog, StopAnalysis
from gads.core.normalize import records_from_snapshot

QUERY = "account_activity"
DEFAULT_LOOKBACK_DAYS = 365


@dataclass
class Activity:
    searched: tuple[date, date]
    last_active: date | None   # None: no day with impressions in the searched period
    active_days: int
    snapshot: Path

    def suggested_period(self, days: int) -> tuple[date, date] | None:
        """The `days` days ending on the last active day."""
        if self.last_active is None:
            return None
        return self.last_active - timedelta(days=days - 1), self.last_active


def find_last_active(customer_id: str, server_cmd: list[str], env: dict, raw_dir: Path, end: date,
                     lookback_days: int = DEFAULT_LOOKBACK_DAYS, queries_dir: Path = ROOT / "queries") -> Activity:
    """Search the lookback_days days ending on `end`. Days with zero impressions are ignored even if the server
    returns them. Raises StopAnalysis on a failed fetch or a response without the required fields."""
    start = end - timedelta(days=lookback_days - 1)
    path = run_snapshot(QUERY, customer_id, start, end, server_cmd, raw_dir, env, queries_dir)
    _, records = records_from_snapshot(path, {"date", "impressions"}, RunLog(), expected_query=QUERY, dated=True)
    active = sorted({r["date"] for r in records if r.get("date") and (r.get("impressions") or 0) > 0})
    if active and (active[0] < start or active[-1] > end):
        raise StopAnalysis(f"{QUERY} returned dates {active[0]} to {active[-1]} outside the requested period "
                           f"{start} to {end}: the date filter is not being applied")
    return Activity((start, end), active[-1] if active else None, len(active), path)
