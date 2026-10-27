#!/usr/bin/env python3
"""List UNKNOWN fields in context/*.md, split into blockers and optional context, and write
a data-readiness checklist to outputs/onboarding/data-readiness.md.

Usage: python3 scripts/context_status.py [--context-dir context] [--out outputs/onboarding]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.onboarding.context import readiness_markdown, scan_context  # noqa: E402

from gads.core.files import ROOT  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context-dir", type=Path, default=ROOT / "context")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "onboarding")
    args = ap.parse_args(argv)
    fields = scan_context(args.context_dir)
    snapshots = sorted(p.name for p in (ROOT / "data" / "raw").glob("*.json"))
    md = readiness_markdown(fields, (ROOT / ".mcp.json").exists(), snapshots)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "data-readiness.md").write_text(md, encoding="utf-8")
    blockers = [f for f in fields if f.blocking]
    print(f"{len(blockers)} blocker(s), {len(fields) - len(blockers)} optional UNKNOWN field(s)")
    for f in blockers:
        print(f"BLOCKER  {f.file} › {f.name}")
    print(args.out / "data-readiness.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
