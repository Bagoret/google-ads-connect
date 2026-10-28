#!/usr/bin/env python3
"""Run one GAQL query from queries/ through the Google Ads MCP server and save the
verbatim response to data/raw/. Read-only: only allowlisted MCP tools can be called.

Usage:
  python3 scripts/snapshot.py --query campaign_daily --customer-id 123-456-7890 \
      --start 2026-10-06 --end 2026-10-19
The server command and env come from .mcp.json ("google-ads-mcp") unless --server-cmd is given.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.connect.mcp_config import server_command  # noqa: E402
from gads.connect.snapshot import run_snapshot  # noqa: E402
from gads.core.files import ROOT  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="query name in queries/ (without .gaql)")
    ap.add_argument("--customer-id", required=True)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--server-cmd", help="override server command (quoted string)")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args(argv)
    try:
        cmd, env = server_command(args.server_cmd, ROOT / ".mcp.json")
        path = run_snapshot(args.query, args.customer_id, args.start, args.end, cmd, args.raw_dir, env)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
