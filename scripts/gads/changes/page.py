"""Change-request status page and the short text summaries shared with the CLI's list command."""
from __future__ import annotations

from datetime import datetime
from html import escape

from gads.changes.store import approval_valid, entity, summary
from gads.changes.pipeline import ChangeRequest, validate_change
from gads.ui.viz import badge, page, tile

STATUS_ORDER = ["proposed", "approved", "rejected", "executed", "verified", "rolled_back"]
STATUS_BADGES = {
    "proposed": ("neutral", "○", "Proposed"), "approved": ("good", "✓", "Approved"),
    "rejected": ("neutral", "✕", "Rejected"), "executed": ("good", "▶", "Executed"),
    "verified": ("good", "✓", "Verified"), "rolled_back": ("warning", "↺", "Rolled back"),
}


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
        if cr.approval and not approval_valid(cr):
            flags.append(badge("critical", "■", "Approval void (edited after approval)"))
        errors = validate_change(cr)
        if errors:
            flags.append(badge("critical", "■", "Invalid request"))
        last = cr.history[-1] if cr.history else None
        history = "".join(f'<li>{escape(h.get("at", "")[:16])} · {escape(h.get("from", ""))} → '
                          f'{escape(h.get("to", ""))} by {escape(h.get("actor", ""))}'
                          + (f' — {escape(h["note"])}' if h.get("note") else "") + "</li>" for h in cr.history)
        meta = [f"Account {escape(cr.customer_id)}", escape(entity(cr))]
        if cr.approval:
            meta.append(f"Approved by {escape(cr.approval['approver'])}")
        meta.append(f"Last change {escape(last['at'][:16]) + ' UTC' if last else '–'}")
        meta.append(f'Fingerprint <span class="mono" title="{escape(cr.fingerprint())}">'
                    f'{escape(cr.fingerprint()[:12])}…</span>')
        items.append(
            f'<li class="request" data-request="{escape(rid)}"><div class="req-head">{" ".join(flags)}'
            f'<span class="mono">{escape(rid)}</span></div>'
            f'<div class="issue-title">{escape(cr.operation)}: {escape(summary(cr))}</div>'
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
