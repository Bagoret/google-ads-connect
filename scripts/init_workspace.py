#!/usr/bin/env python3
"""Create the business workspace (context/ and per-business config) from templates/.

  python3 scripts/init_workspace.py                 # create missing files; never overwrites
  python3 scripts/init_workspace.py --reset --yes   # start over for a NEW business (overwrites context!)

Use --reset only in a fresh copy of the system for another business: it replaces every filled-in
business fact with the empty template.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# template path (relative to templates/) -> workspace path (relative to repo root)
MAPPING = {
    "context/business.md": "context/business.md",
    "context/account-map.md": "context/account-map.md",
    "context/measurement.md": "context/measurement.md",
    "context/commercial-calendar.md": "context/commercial-calendar.md",
    "config/brand_lists.json": "config/brand_lists.json",
    "config/campaign_classification.json": "config/campaign_classification.json",
}


def init_workspace(root: Path = ROOT, reset: bool = False, confirm: bool = False) -> dict:
    if reset and not confirm:
        raise ValueError("reset overwrites all business context; pass confirm=True (--yes) to proceed")
    result: dict[str, list[str]] = {"created": [], "kept": [], "reset": []}
    for src_rel, dst_rel in MAPPING.items():
        src, dst = root / "templates" / src_rel, root / dst_rel
        if not src.exists():
            raise FileNotFoundError(f"template missing: templates/{src_rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not reset:
            result["kept"].append(dst_rel)
            continue
        key = "reset" if dst.exists() else "created"
        shutil.copyfile(src, dst)
        result[key].append(dst_rel)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="overwrite business files with empty templates")
    ap.add_argument("--yes", action="store_true", help="confirm --reset")
    args = ap.parse_args(argv)
    try:
        result = init_workspace(ROOT, reset=args.reset, confirm=args.yes)
    except ValueError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    for key in ("created", "reset", "kept"):
        for path in result[key]:
            print(f"{key:7} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
