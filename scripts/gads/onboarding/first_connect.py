"""First-connection check: fetch every library query once, run the contract gate on each, and say which features
can run on this account. Raw snapshots are kept verbatim in data/raw/; the result holds only field names, counts and
statuses (no account values), so the report can be shared."""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from gads.connect.snapshot import run_snapshot
from gads.core.contracts import QUERY_REQUIRED
from gads.core.files import ROOT
from gads.core.inspect import inspect_snapshot
from gads.core.logbook import StopAnalysis
from gads.core.normalize import load_field_map

# feature -> (queries it needs, optional queries). Order is the order of the report.
FEATURES: list[tuple[str, list[str], list[str]]] = [
    ("Onboarding (account facts)", ["customer_settings", "campaign_inventory", "conversion_actions"], []),
    ("Weekly review and dashboard", ["campaign_daily"], []),
    ("Search-term review", ["search_terms", "keywords", "negative_keywords"],
     ["shared_negative_keywords", "campaign_shared_sets"]),
    ("Product review", ["product_daily"], []),
]


@dataclass
class QueryResult:
    query: str
    status: str            # PASS | EMPTY | FAIL
    rows: int = 0
    detail: str = ""
    missing: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    snapshot: str = ""
    date_range: list[str] | None = None


@dataclass
class FirstConnect:
    customer_id: str
    period: tuple[date, date]
    queries: list[QueryResult]
    features: list[dict]

    @property
    def failed(self) -> bool:
        return any(q.status == "FAIL" for q in self.queries)


def _dated(query_path: Path) -> bool:
    return "{start}" in query_path.read_text(encoding="utf-8")


def check_query(name: str, customer_id: str, period: tuple[date, date], server_cmd: list[str], env: dict,
                raw_dir: Path, queries_dir: Path) -> QueryResult:
    start, end = period if _dated(queries_dir / f"{name}.gaql") else (None, None)
    try:
        path = run_snapshot(name, customer_id, start, end, server_cmd, raw_dir, env, queries_dir)
        info = inspect_snapshot(path)
    except StopAnalysis as exc:
        return QueryResult(name, "FAIL", detail=exc.reason[:500])
    except Exception as exc:  # noqa: BLE001 - a diagnostic run continues with the next query; traceback is printed
        traceback.print_exc(file=sys.stderr)
        return QueryResult(name, "FAIL", detail=f"unexpected error: {type(exc).__name__}: {exc}"[:500])
    unmapped = sorted(set(info["raw_fields"]) - set(load_field_map()))
    result = QueryResult(name, "PASS", rows=info["rows"], unmapped=unmapped, snapshot=Path(path).name,
                         date_range=info["date_range"])
    if info["rows"] == 0:
        result.status = "EMPTY"
        result.detail = "no rows returned: the response shape is valid but the required fields could not be checked"
        if start:
            result.detail += (f" (no activity {start} to {end}; if the campaigns are paused, re-run with --end set to "
                              "a day when they were running, e.g. --end 2026-06-30 --days 30)")
        return result
    result.missing = sorted(QUERY_REQUIRED.get(name, frozenset()) - set(info["canonical_fields"]))
    if result.missing:
        result.status = "FAIL"
        result.detail = "required field(s) missing from the response: " + ", ".join(result.missing)
    elif start and info["date_range"] and (info["date_range"][0] < str(start) or info["date_range"][1] > str(end)):
        result.status = "FAIL"
        result.detail = (f"returned dates {info['date_range'][0]} to {info['date_range'][1]} fall outside the requested "
                         f"period {start} to {end}: the query's date filter is not being applied")
    return result


def feature_status(results: dict[str, QueryResult]) -> list[dict]:
    out = []
    for feature, needed, optional in FEATURES:
        statuses = [results[q].status for q in needed if q in results]
        if any(s == "FAIL" for s in statuses):
            status = "BLOCKED"
        elif any(s == "EMPTY" for s in statuses):
            status = "NO DATA"
        else:
            status = "READY"
        notes = [f"optional {q}: {results[q].status}" for q in optional if q in results and results[q].status != "PASS"]
        out.append({"feature": feature, "status": status, "needs": needed, "notes": notes})
    return out


def run(customer_id: str, period: tuple[date, date], server_cmd: list[str], env: dict, raw_dir: Path,
        queries_dir: Path = ROOT / "queries", progress=None) -> FirstConnect:
    names = sorted(p.stem for p in queries_dir.glob("*.gaql"))
    results = {}
    for i, name in enumerate(names, 1):
        if progress:
            progress(f"[{i}/{len(names)}] {name} …")
        results[name] = check_query(name, customer_id, period, server_cmd, env, raw_dir, queries_dir)
        if progress:
            progress(f"        {results[name].status}" + (f" ({results[name].rows} rows)" if results[name].rows else ""))
    return FirstConnect(customer_id, period, [results[n] for n in names], feature_status(results))
