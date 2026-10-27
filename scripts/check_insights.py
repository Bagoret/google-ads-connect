#!/usr/bin/env python3
"""Check AI-written insights against a dashboard's facts before showing them.

  python3 scripts/check_insights.py --facts outputs/dashboard_<...>/facts.json --insights insights.json

insights.json: {"insights": [{"kind": "issue"|"opportunity", "label": "Observed"|"Hypothesis"|"Recommendation",
  "title": "...", "text": "... {{fact.key}} ...", "entity_type": "campaign", "entity_id": "123",
  "evidence": ["fact.key", ...], "confidence": "low"|"medium"|"high"}]}
Numbers may appear only as {{fact.key}} placeholders (entity IDs and period dates excepted).
Exit code 1 if any insight is rejected (they are dropped from the dashboard).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.ai.insights import validate_insights  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", type=Path, required=True)
    ap.add_argument("--insights", type=Path, required=True)
    args = ap.parse_args(argv)
    facts = json.loads(args.facts.read_text(encoding="utf-8")).get("facts", {})
    ok, rejected = validate_insights(json.loads(args.insights.read_text(encoding="utf-8")), facts)
    print(f"{len(ok)} verified, {len(rejected)} rejected")
    for r in rejected:
        print(f"- REJECTED #{r['index']} {r['title'] or '(untitled)'}: {'; '.join(r['reasons'])}")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
