"""Command-line plumbing shared by the scripts: common flags, JSON config loading, optional parts, exit codes.

Exit codes: 0 = done · 2 = stopped (reason printed, nothing written) · 3 = done, but an optional part (a dashboard
page, the AI section) failed and was skipped; its full traceback is printed. Set GADS_STRICT=1 to make optional parts
fail loudly instead (for debugging)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from gads.core.logbook import StopAnalysis
from gads.core.files import ROOT


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


SKIPPED: list[str] = []  # optional parts skipped in this run


def strict() -> bool:
    return os.environ.get("GADS_STRICT") == "1"


def guarded(label: str, fn, fallback=None):
    """Run an optional part. If it fails, print its full traceback, remember it, and return fallback (or
    fallback(exc) if it is callable), so the main outputs are unaffected. Disk errors (OSError) and GADS_STRICT=1
    runs are never swallowed."""
    try:
        return fn()
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate fault isolation for optional parts only
        if strict():
            raise
        print(f"Warning: {label} skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        SKIPPED.append(label)
        return fallback(exc) if callable(fallback) else fallback


def write_optional(path: Path, render, label: str = "page") -> bool:
    """Write an optional output (e.g. a dashboard page) via guarded(). Returns True if written."""
    text = guarded(f"{path.name} ({label})", render)
    if text is None:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def finish(result) -> int:
    """Print the result path; exit 3 if optional parts were skipped (summary on stderr), else 0."""
    print(result)
    if SKIPPED:
        n = len(SKIPPED)
        print(f"Finished with {n} optional part{'s' if n > 1 else ''} skipped: {'; '.join(SKIPPED)} "
              "(main outputs written; see the traceback above; GADS_STRICT=1 to fail loudly)", file=sys.stderr)
        return 3
    return 0


def run_cli(fn, args) -> int:
    """Run fn(args); print its result path. Exit 2 with the STOP reason (nothing written), or see finish()."""
    SKIPPED.clear()
    try:
        result = fn(args)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    return finish(result)
