"""Approval-gated change pipeline. Phase 1 ships NO executor that can reach an account:
DisabledExecutor always refuses, and config/execution.json has writes_enabled = false.

Lifecycle: proposed -> approved | rejected; approved -> executed | proposed (re-opened);
executed -> verified | rolled_back. Approval is bound to a fingerprint of the exact change, so any
edit after approval invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

OPERATIONS: dict[str, frozenset[str]] = {
    "pause_campaign": frozenset({"campaign_id"}),
    "enable_campaign": frozenset({"campaign_id"}),
    "set_campaign_budget": frozenset({"campaign_id", "budget_id", "amount_micros_before", "amount_micros_after"}),
    "set_campaign_target_roas": frozenset({"campaign_id", "before", "after"}),
    "set_campaign_target_cpa": frozenset({"campaign_id", "before_micros", "after_micros"}),
    "pause_ad_group": frozenset({"ad_group_id"}),
    "pause_keyword": frozenset({"ad_group_id", "criterion_id"}),
    "add_campaign_negative_keyword": frozenset({"campaign_id", "text", "match_type"}),
    "add_shared_negative_keyword": frozenset({"shared_set_id", "text", "match_type"}),
}

TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"approved", "rejected"}),
    "approved": frozenset({"executed", "proposed"}),
    "executed": frozenset({"verified", "rolled_back"}),
    "rejected": frozenset(),
    "verified": frozenset(),
    "rolled_back": frozenset(),
}
STATUSES = tuple(TRANSITIONS)
MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}
BEFORE_AFTER = [("amount_micros_before", "amount_micros_after"), ("before", "after"), ("before_micros", "after_micros")]


class IllegalTransition(Exception):
    pass


class WritesDisabled(Exception):
    pass


@dataclass
class ChangeRequest:
    id: str
    customer_id: str
    operation: str
    params: dict
    rationale: str
    evidence: str
    status: str = "proposed"
    approval: dict | None = None
    history: list[dict] = field(default_factory=list)

    def fingerprint(self) -> str:
        canonical = json.dumps({"customer_id": self.customer_id, "operation": self.operation, "params": self.params},
                               sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeRequest":
        return cls(**data)


def validate_change(cr: ChangeRequest) -> list[str]:
    errors = []
    if not re.fullmatch(r"\d{10}", cr.customer_id or ""):
        errors.append("customer_id must be 10 digits")
    required = OPERATIONS.get(cr.operation)
    if required is None:
        return errors + [f"unknown operation {cr.operation!r}"]
    keys = set(cr.params)
    if required - keys:
        errors.append(f"missing params: {sorted(required - keys)}")
    if keys - required:
        errors.append(f"unexpected params: {sorted(keys - required)}")
    if "match_type" in cr.params and cr.params["match_type"] not in MATCH_TYPES:
        errors.append(f"match_type must be one of {sorted(MATCH_TYPES)}")
    for before, after in BEFORE_AFTER:
        if before in cr.params and after in cr.params and cr.params[before] == cr.params[after]:
            errors.append(f"{before} equals {after}: no-op change")
    return errors


def transition(cr: ChangeRequest, new_status: str, actor: str, at: datetime, note: str = "") -> None:
    if new_status not in TRANSITIONS.get(cr.status, frozenset()):
        raise IllegalTransition(f"{cr.status} -> {new_status} is not allowed")
    cr.history.append({"from": cr.status, "to": new_status, "actor": actor, "at": at.isoformat(), "note": note})
    cr.status = new_status
    if new_status == "proposed":
        cr.approval = None


def approve(cr: ChangeRequest, approver: str, fingerprint: str, at: datetime) -> None:
    if not approver or not approver.strip():
        raise ValueError("approver is required")
    errors = validate_change(cr)
    if errors:
        raise ValueError(f"invalid change request: {errors}")
    if fingerprint != cr.fingerprint():
        raise ValueError("fingerprint does not match the change request; re-review before approving")
    transition(cr, "approved", approver.strip(), at)
    cr.approval = {"approver": approver.strip(), "at": at.isoformat(), "fingerprint": fingerprint}


class DisabledExecutor:
    """The only executor in Phase 1. It never contacts any API."""

    def execute(self, cr: ChangeRequest) -> dict:
        raise WritesDisabled("no write executor is installed (Phase 1); see docs/write-path.md")


def execute_change(cr: ChangeRequest, executor, config: dict) -> dict:
    if config.get("writes_enabled") is not True:
        raise WritesDisabled("writes are disabled in config/execution.json")
    if cr.status != "approved" or not cr.approval:
        raise PermissionError(f"change {cr.id} is {cr.status}, not approved")
    if cr.approval.get("fingerprint") != cr.fingerprint():
        raise PermissionError(f"change {cr.id} was modified after approval; approval is void")
    return executor.execute(cr)


def record_approved(cr: ChangeRequest, change_log: Path) -> None:
    if cr.status not in {"approved", "executed", "verified", "rolled_back"} or not cr.approval:
        raise PermissionError(f"only approved changes are recorded; {cr.id} is {cr.status}")
    before_after = next((f"{cr.params[b]} → {cr.params[a]}" for b, a in BEFORE_AFTER if b in cr.params), "")
    entity = next((f"{k}={v}" for k, v in cr.params.items() if k.endswith("_id")), "")
    row = (f"| {cr.approval['at'][:10]} | | {cr.customer_id} / {entity} | {cr.id}: {cr.operation} "
           f"{json.dumps(cr.params, sort_keys=True)} | {before_after} | {cr.evidence} | {cr.approval['approver']} | | | |")
    with open(change_log, "a", encoding="utf-8") as fh:
        fh.write(row + "\n")


def save_request(cr: ChangeRequest, root: Path = Path("outputs/change-requests")) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{cr.id}_{len(cr.history):02d}_{cr.status}.json"
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(cr.to_dict(), fh, indent=2, ensure_ascii=False, default=str)
    return path
