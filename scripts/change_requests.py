#!/usr/bin/env python3
"""Track proposed account changes through approval, and show their status on an offline page.
Nothing here can change an ad account: there is no executor (see docs/write-path.md).

  python3 scripts/change_requests.py propose --operation pause_campaign --customer-id 123-456-7890 \
      --param campaign_id=111 --rationale "..." --evidence outputs/<review>/report.md
  python3 scripts/change_requests.py approve --id CR-... --approver "Name" --fingerprint <64 hex>
  python3 scripts/change_requests.py reject  --id CR-... --actor "Name" [--note "..."]
  python3 scripts/change_requests.py reopen  --id CR-... --actor "Name" [--note "..."]
  python3 scripts/change_requests.py list
  python3 scripts/change_requests.py view     # writes outputs/change-requests/status.html

Approval is a human decision: only run `approve` when the approver has explicitly approved that
request ID and fingerprint. Every revision is saved as a new file; nothing is overwritten.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.ids import parse_customer_id  # noqa: E402
from gads.changes import (BEFORE_AFTER, ChangeRequest, IllegalTransition, approve, record_approved,  # noqa: E402
                          save_request, transition, validate_change)
from gads.viz import badge, page, tile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATUS_ORDER = ["proposed", "approved", "rejected", "executed", "verified", "rolled_back"]
STATUS_BADGES = {
    "proposed": ("neutral", "○", "Proposed"), "approved": ("good", "✓", "Approved"),
    "rejected": ("neutral", "✕", "Rejected"), "executed": ("good", "▶", "Executed"),
    "verified": ("good", "✓", "Verified"), "rolled_back": ("warning", "↺", "Rolled back"),
}


class CliError(Exception):
    pass


TEXT_PARAMS = {"text", "match_type"}  # never converted, so a keyword like "007" keeps its leading zeros


def _customer_id(text: str) -> str:
    cid = parse_customer_id(text)
    if not cid:
        raise CliError(f"not a 10-digit Google Ads customer ID: {text!r}")
    return cid


def _parse_value(key: str, text: str):
    return int(text) if key not in TEXT_PARAMS and re.fullmatch(r"-?\d+", text) else text


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


def _get(requests_dir: Path, rid: str) -> ChangeRequest:
    reqs = load_requests(requests_dir)
    if rid not in reqs:
        raise CliError(f"no change request with id {rid}")
    return reqs[rid]


def _approval_valid(cr: ChangeRequest) -> bool:
    return bool(cr.approval) and cr.approval.get("fingerprint") == cr.fingerprint()


def _before_after(cr: ChangeRequest) -> str:
    for b, a in BEFORE_AFTER:
        if b in cr.params and a in cr.params:
            unit = " micros" if "micros" in b else ""
            return f"{cr.params[b]} → {cr.params[a]}{unit}"
    return "–"


def _summary(cr: ChangeRequest) -> str:
    """What the change does, in words."""
    if "text" in cr.params and "match_type" in cr.params:
        return f'add negative "{cr.params["text"]}" ({cr.params["match_type"]})'
    if cr.operation.startswith(("pause_", "enable_")):
        return cr.operation.split("_", 1)[0]
    return _before_after(cr)


def _entity(cr: ChangeRequest) -> str:
    return ", ".join(f"{k}={v}" for k, v in cr.params.items() if k.endswith("_id")) or "–"


def render_status(reqs: dict[str, ChangeRequest], config: dict, generated_at: datetime) -> str:
    counts = {s: sum(1 for r in reqs.values() if r.status == s) for s in STATUS_ORDER}
    tiles = "".join(tile(STATUS_BADGES[s][2], str(counts[s])) for s in STATUS_ORDER)
    if config.get("writes_enabled") is True:
        banner = ('<div class="banner"><strong>■ writes_enabled is ON in config/execution.json.</strong> Only the '
                  'account owner should set this, and no executor is installed yet.</div>')
    else:
        banner = ('<div class="banner">Writes are disabled (config/execution.json). Approved requests are recorded '
                  'in decisions/change-log.md; nothing is executed in any account.</div>')
    items = []
    for rid, cr in sorted(reqs.items(), key=lambda kv: (STATUS_ORDER.index(kv[1].status)
                                                         if kv[1].status in STATUS_ORDER else 99, kv[0])):
        tone, icon, label = STATUS_BADGES.get(cr.status, ("neutral", "○", cr.status))
        flags = [badge(tone, icon, label)]
        if cr.approval and not _approval_valid(cr):
            flags.append(badge("critical", "■", "Approval void (edited after approval)"))
        errors = validate_change(cr)
        if errors:
            flags.append(badge("critical", "■", "Invalid request"))
        last = cr.history[-1] if cr.history else None
        history = "".join(f'<li>{escape(h.get("at", "")[:16])} · {escape(h.get("from", ""))} → '
                          f'{escape(h.get("to", ""))} by {escape(h.get("actor", ""))}'
                          + (f' — {escape(h["note"])}' if h.get("note") else "") + "</li>" for h in cr.history)
        meta = [f"Account {escape(cr.customer_id)}", escape(_entity(cr))]
        if cr.approval:
            meta.append(f"Approved by {escape(cr.approval['approver'])}")
        meta.append(f"Last change {escape(last['at'][:16]) + ' UTC' if last else '–'}")
        meta.append(f'Fingerprint <span class="mono" title="{escape(cr.fingerprint())}">'
                    f'{escape(cr.fingerprint()[:12])}…</span>')
        items.append(
            f'<li class="request" data-request="{escape(rid)}"><div class="req-head">{" ".join(flags)}'
            f'<span class="mono">{escape(rid)}</span></div>'
            f'<div class="issue-title">{escape(cr.operation)}: {escape(_summary(cr))}</div>'
            + (f'<div class="muted small">{escape("; ".join(errors))}</div>' if errors else "")
            + f'<div class="issue-action">{escape(cr.rationale)}</div>'
            f'<div class="muted small">Evidence: {escape(cr.evidence)}</div>'
            f'<div class="muted small">{" · ".join(meta)}</div>'
            f'<details><summary>History ({len(cr.history)})</summary>'
            f'<ul class="caveats">{history or "<li>No decisions yet.</li>"}</ul></details></li>')
    table = (f'<ul class="requests">{"".join(items)}</ul>' if items else
             '<p class="muted">No change requests yet. Proposals from reviews stay in action registers '
             'until someone creates a request with <code>change_requests.py propose</code>.</p>')
    body = f"""{banner}
<section class="kpis" aria-label="Requests by status">{tiles}</section>
<section class="card"><h2>Change requests</h2>
<p class="muted small">An approval is tied to a fingerprint of the exact change; editing a request after approval
voids it. Each revision is a separate file in outputs/change-requests/.</p>{table}</section>"""
    footer = f"{len(reqs)} request(s) · generated {escape(generated_at.isoformat(timespec='seconds'))}"
    return page("Change requests", "Status of proposed account changes · nothing here changes an account",
                False, body, footer)


def cmd_propose(args) -> str:
    params = {}
    for item in args.param or []:
        if "=" not in item:
            raise CliError(f"--param must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        params[key.strip()] = _parse_value(key.strip(), value.strip())
    now = datetime.now(timezone.utc)
    cr = ChangeRequest(id=f"CR-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
                       customer_id=_customer_id(args.customer_id), operation=args.operation, params=params,
                       rationale=args.rationale, evidence=args.evidence)
    errors = validate_change(cr)
    if errors:
        raise CliError("invalid change request: " + "; ".join(errors))
    save_request(cr, args.requests_dir)
    return (f"id: {cr.id}\nfingerprint: {cr.fingerprint()}\nstatus: proposed\n"
            "Approve only after the approver has reviewed this exact request and fingerprint.")


def cmd_approve(args) -> str:
    cr = _get(args.requests_dir, args.id)
    try:
        approve(cr, args.approver, args.fingerprint, datetime.now(timezone.utc))
    except (ValueError, IllegalTransition) as exc:
        raise CliError(str(exc))
    save_request(cr, args.requests_dir)
    record_approved(cr, args.change_log)
    return f"{cr.id} approved by {cr.approval['approver']}; recorded in {args.change_log}"


def _move(args, status: str) -> str:
    cr = _get(args.requests_dir, args.id)
    try:
        transition(cr, status, args.actor, datetime.now(timezone.utc), args.note or "")
    except IllegalTransition as exc:
        raise CliError(str(exc))
    save_request(cr, args.requests_dir)
    return f"{cr.id} is now {status}"


def cmd_list(args) -> str:
    reqs = load_requests(args.requests_dir)
    if not reqs:
        return "No change requests."
    return "\n".join(f"{rid}  {cr.status:<11} {cr.operation:<30} {_entity(cr)}"
                     + ("  [APPROVAL VOID]" if cr.approval and not _approval_valid(cr) else "")
                     for rid, cr in reqs.items())


def cmd_view(args) -> str:
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if Path(args.config).exists() else {}
    html = render_status(load_requests(args.requests_dir), config, datetime.now(timezone.utc))
    Path(args.requests_dir).mkdir(parents=True, exist_ok=True)
    out = Path(args.requests_dir) / "status.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--requests-dir", type=Path, default=ROOT / "outputs" / "change-requests")
    common.add_argument("--change-log", type=Path, default=ROOT / "decisions" / "change-log.md")
    common.add_argument("--config", type=Path, default=ROOT / "config" / "execution.json")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", parents=[common])
    p.add_argument("--operation", required=True)
    p.add_argument("--customer-id", required=True)
    p.add_argument("--param", action="append", help="key=value (repeat)")
    p.add_argument("--rationale", required=True)
    p.add_argument("--evidence", required=True, help="report path, date range, metrics")
    a = sub.add_parser("approve", parents=[common])
    a.add_argument("--id", required=True)
    a.add_argument("--approver", required=True)
    a.add_argument("--fingerprint", required=True)
    for name in ("reject", "reopen"):
        s = sub.add_parser(name, parents=[common])
        s.add_argument("--id", required=True)
        s.add_argument("--actor", required=True)
        s.add_argument("--note")
    sub.add_parser("list", parents=[common])
    sub.add_parser("view", parents=[common])
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"propose": cmd_propose, "approve": cmd_approve, "list": cmd_list, "view": cmd_view,
                "reject": lambda a: _move(a, "rejected"), "reopen": lambda a: _move(a, "proposed")}
    try:
        print(handlers[args.cmd](args))
    except CliError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
