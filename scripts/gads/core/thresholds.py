"""Analysis sensitivity thresholds from config/review_thresholds.json, validated once for every review."""
from __future__ import annotations

import math
from pathlib import Path

from gads.core.cli import load_json_file
from gads.core.files import ROOT
from gads.core.logbook import StopAnalysis

REQUIRED_THRESHOLDS = ("min_clicks_for_ratio",)
OPTIONAL_THRESHOLDS = ("material_pct_change", "min_spend_zero_conv", "min_conversions_for_ratio")


def check_thresholds(thresholds: dict) -> dict:
    """Required values must be non-negative numbers; optional ones may also be null (rule disabled)."""
    for key in REQUIRED_THRESHOLDS + OPTIONAL_THRESHOLDS:
        value = thresholds.get(key)
        if value is None and key in OPTIONAL_THRESHOLDS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise StopAnalysis(f"config/review_thresholds.json: {key} must be a non-negative number"
                               + (" or null" if key in OPTIONAL_THRESHOLDS else ""))
    return thresholds


def load_thresholds(path: Path = ROOT / "config" / "review_thresholds.json") -> dict:
    return check_thresholds(load_json_file(path, "thresholds file"))
