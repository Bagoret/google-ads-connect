"""Reading saved change requests (outputs/change-requests/<id>_<NN>_<status>.json)."""
from __future__ import annotations

import json
from pathlib import Path

from gads.changes.pipeline import ChangeRequest


def load_requests(requests_dir: Path) -> dict[str, ChangeRequest]:
    """Latest revision of each request (files are <id>_<NN>_<status>.json, NN = history length)."""
    latest: dict[str, tuple[int, Path]] = {}
    for path in Path(requests_dir).glob("*.json"):
        parts = path.stem.split("_", 2)  # ids contain no "_"; statuses can ("rolled_back")
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        rid, rev = parts[0], int(parts[1])
        if rid not in latest or rev > latest[rid][0]:
            latest[rid] = (rev, path)
    return {rid: ChangeRequest.from_dict(json.loads(p.read_text(encoding="utf-8")))
            for rid, (_, p) in sorted(latest.items())}


def approval_valid(cr: ChangeRequest) -> bool:
    return bool(cr.approval) and cr.approval.get("fingerprint") == cr.fingerprint()
