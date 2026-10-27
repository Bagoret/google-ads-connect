"""Saved change requests (outputs/change-requests/<id>_<NN>_<status>.json): loading, approval check, and short
text descriptions shared by the CLI's list command and the status page."""
from __future__ import annotations

import json
from pathlib import Path

from gads.changes.pipeline import BEFORE_AFTER, ChangeRequest


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


def before_after(cr: ChangeRequest) -> str:
    for b, a in BEFORE_AFTER:
        if b in cr.params and a in cr.params:
            unit = " micros" if "micros" in b else ""
            return f"{cr.params[b]} → {cr.params[a]}{unit}"
    return "–"


def summary(cr: ChangeRequest) -> str:
    """What the change does, in words."""
    if "text" in cr.params and "match_type" in cr.params:
        return f'add negative "{cr.params["text"]}" ({cr.params["match_type"]})'
    if cr.operation.startswith(("pause_", "enable_")):
        return cr.operation.split("_", 1)[0]
    return before_after(cr)


def entity(cr: ChangeRequest) -> str:
    return ", ".join(f"{k}={v}" for k, v in cr.params.items() if k.endswith("_id")) or "–"
