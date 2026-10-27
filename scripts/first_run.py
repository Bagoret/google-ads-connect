#!/usr/bin/env python3
"""First-run state for the person using this checkout, and the SessionStart hook message.

  python3 scripts/first_run.py --status         # JSON: workspace, profile, blockers, MCP config
  python3 scripts/first_run.py --hook           # prints a reminder only when setup is incomplete
  python3 scripts/first_run.py save --relationship agency --access read_only \
      --uses weekly-review,search-term-review [--name "Sam"]

The profile lives in local/profile.json (gitignored, private to this machine). It holds no email,
no credentials, and nothing about customers.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.setup.context import scan_context  # noqa: E402
from gads.core.files import write_private_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RELATIONSHIPS = {"owner", "employee", "agency", "freelancer", "consultant", "client", "other"}
ACCESS_LEVELS = {"admin", "standard", "read_only", "billing", "email_only", "none", "unknown"}
USES = {"weekly-review", "search-term-review", "product-review", "onboarding", "explore"}


def profile_path(root: Path) -> Path:
    return root / "local" / "profile.json"


def load_profile(root: Path) -> dict | None:
    path = profile_path(root)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_profile(root: Path, relationship: str, access: str, uses: list[str],
                 display_name: str | None = None, now: datetime | None = None) -> Path:
    if relationship not in RELATIONSHIPS:
        raise ValueError(f"relationship must be one of {sorted(RELATIONSHIPS)}")
    if access not in ACCESS_LEVELS:
        raise ValueError(f"access must be one of {sorted(ACCESS_LEVELS)}")
    unknown = set(uses) - USES
    if not uses or unknown:
        raise ValueError(f"uses must be a non-empty subset of {sorted(USES)}")
    path = profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "display_name": (display_name or "").strip()[:60],
        "relationship": relationship,
        "access": access,
        "uses": sorted(set(uses)),
        "first_run_completed_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    write_private_json(path, data)
    return path


def status(root: Path = ROOT) -> dict:
    context_dir = root / "context"
    initialised = (context_dir / "business.md").exists()
    fields = scan_context(context_dir) if initialised else []
    return {
        "context_initialised": initialised,
        "profile": profile_path(root).exists(),
        "business_blockers": sum(1 for f in fields if f.blocking),
        "mcp_configured": (root / ".mcp.json").exists(),
    }


def hook_message(st: dict) -> str:
    todo = []
    if not st["context_initialised"]:
        todo.append("No business workspace yet: run `python3 scripts/init_workspace.py`, then the onboarding "
                    "skill (part 1 person setup, then part 2 business).")
    elif not st["profile"]:
        todo.append("New person on this machine (no local/profile.json): run the onboarding skill, part 1 "
                    "(person setup), before other work.")
    if st["context_initialised"] and st["business_blockers"]:
        todo.append(f"{st['business_blockers']} business blocker(s) remain in context/: onboarding part 2 "
                    "can resolve them.")
    if not st["mcp_configured"]:
        todo.append("Google Ads not connected (.mcp.json missing): see docs/mcp-setup.md, then "
                    "`python3 scripts/check_connection.py --live`.")
    if not todo:
        return ""
    return "Google Ads OS first-run check:\n- " + "\n- ".join(todo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--hook", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    save = sub.add_parser("save", help="save this person's profile")
    save.add_argument("--relationship", required=True, choices=sorted(RELATIONSHIPS))
    save.add_argument("--access", required=True, choices=sorted(ACCESS_LEVELS))
    save.add_argument("--uses", required=True, help="comma-separated: " + ",".join(sorted(USES)))
    save.add_argument("--name", help="optional display name or initials")
    args = ap.parse_args(argv)
    if args.cmd == "save":
        try:
            path = save_profile(ROOT, args.relationship, args.access,
                                [u.strip() for u in args.uses.split(",") if u.strip()], args.name)
        except ValueError as exc:
            print(f"STOP: {exc}", file=sys.stderr)
            return 2
        print(path)
        return 0
    st = status(ROOT)
    if args.hook:
        msg = hook_message(st)
        if msg:
            print(msg)
        return 0
    print(json.dumps(st, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
