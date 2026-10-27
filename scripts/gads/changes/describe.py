"""Short text descriptions of a change request, shared by the CLI's list command and the status page."""
from __future__ import annotations

from gads.changes.pipeline import BEFORE_AFTER, ChangeRequest


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
