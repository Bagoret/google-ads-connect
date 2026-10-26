"""Command-line plumbing shared by the review scripts: common flags, config loading, exit codes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .findings import check_thresholds
from .logbook import StopAnalysis

ROOT = Path(__file__).resolve().parent.parent.parent


def add_common_args(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    ap.add_argument("--expected-currency")
    ap.add_argument("--timezone", help="only if the snapshot lacks customer.time_zone")
    ap.add_argument("--conversion-lag-days", type=int)
    ap.add_argument("--now", help="ISO-8601 timestamp for partial-data checks (default: now; no offset = UTC)")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    return ap


def load_json_file(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise StopAnalysis(f"cannot read {what} {path}: {exc.strerror or exc}")
    except ValueError:
        raise StopAnalysis(f"{what} {path} is not valid JSON")


def load_thresholds(path: Path = ROOT / "config" / "review_thresholds.json") -> dict:
    return check_thresholds(load_json_file(path, "thresholds file"))


def run_cli(fn, args) -> int:
    """Run fn(args); print its result path, or the STOP reason with exit code 2 (nothing written)."""
    try:
        result = fn(args)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    print(result)
    return 0
