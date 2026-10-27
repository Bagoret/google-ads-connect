"""Analysis settings from config/ (review sensitivity thresholds)."""
from __future__ import annotations

from pathlib import Path

from gads.analysis.findings import check_thresholds
from gads.core.cli import load_json_file
from gads.core.paths import ROOT


def load_thresholds(path: Path = ROOT / "config" / "review_thresholds.json") -> dict:
    return check_thresholds(load_json_file(path, "thresholds file"))
