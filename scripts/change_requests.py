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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.core.ids import parse_customer_id  # noqa: E402
from gads.changes.pipeline import (ChangeRequest, IllegalTransition, approve, record_approved,  # noqa: E402
                          save_request, transition, validate_change)
from gads.changes.store import approval_valid, entity, load_requests  # noqa: E402

from gads.core.files import ROOT  # noqa: E402


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


def _get(requests_dir: Path, rid: str) -> ChangeRequest:
    reqs = load_requests(requests_dir)
    if rid not in reqs:
        raise CliError(f"no change request with id {rid}")
    return reqs[rid]


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
    return "\n".join(f"{rid}  {cr.status:<11} {cr.operation:<30} {entity(cr)}"
                     + ("  [APPROVAL VOID]" if cr.approval and not approval_valid(cr) else "")
                     for rid, cr in reqs.items())


def cmd_view(args) -> str:
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if Path(args.config).exists() else {}
    from gads.changes.page import render_status  # only `view` needs the page code
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
