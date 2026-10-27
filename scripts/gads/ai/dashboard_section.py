"""The dashboard's AI parts: facts.json, the verified "AI analysis" section and the "Ask about this data" box.

dashboard.py builds these behind a guard: if anything here fails, the rest of the dashboard still renders."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from gads.ai.insights import build_facts, validate_insights
from gads.core.cli import guarded
from gads.weekly.analysis import Review
from gads.ui.viz import badge

ASK_JS = """
(function(){
  var sec = document.getElementById('ask'); if (!sec) return;
  var tok = sec.getAttribute('data-token');
  var live = location.protocol.indexOf('http') === 0 && tok && tok !== '__ASK_' + 'TOKEN__';
  sec.querySelector('.ask-off').hidden = live; sec.querySelector('form').hidden = !live;
  if (!live) return;
  var form = sec.querySelector('form'), out = sec.querySelector('.ask-answer'), warn = sec.querySelector('.ask-warn');
  form.addEventListener('submit', function(e){
    e.preventDefault();
    var q = form.querySelector('textarea').value; if (!q.trim()) return;
    out.textContent = 'Thinking…'; warn.textContent = ''; form.querySelector('button').disabled = true;
    fetch('/ask', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Ask-Token': tok},
                   body: JSON.stringify({question: q})})
      .then(function(r){ return r.json().then(function(d){ return {ok: r.ok, d: d}; }); })
      .then(function(res){
        out.textContent = res.ok ? res.d.answer : ('Error: ' + (res.d.error || 'request failed'));
        if (res.ok && res.d.unverified && res.d.unverified.length)
          warn.textContent = 'Not in the facts: ' + res.d.unverified.join('; ');
      })
      .catch(function(){ out.textContent = 'Error: the local ask server is not reachable.'; })
      .finally(function(){ form.querySelector('button').disabled = false; });
  });
})();
"""

KIND_BADGE = {"issue": ("serious", "▲", "Issue"), "opportunity": ("good", "◆", "Opportunity")}


def ai_section(insights_path: Path | None, facts: dict[str, str]) -> str:
    intro = ('<p class="muted small">Written by Claude from this dashboard&#39;s numbers. Every number was checked '
             'against the engine output; insights citing anything else are dropped. Hypotheses are unverified; '
             'recommendations need your approval.</p>')
    if not insights_path:
        return ('<section class="card"><h2>AI analysis</h2><p class="muted">No AI analysis yet. Ask Claude to run the '
                'weekly-review skill (it writes insights and rebuilds this page), or use the Ask box below.</p></section>')
    data = json.loads(Path(insights_path).read_text(encoding="utf-8"))
    ok, rejected = validate_insights(data, facts)
    groups = []
    for kind, heading in (("issue", "Issues"), ("opportunity", "Opportunities")):
        items = [i for i in ok if i["kind"] == kind]
        cards = "".join(
            f'<li class="request"><div class="req-head">{badge(*KIND_BADGE[kind])}{badge("neutral", "○", i["label"])}'
            f'<span class="muted small">confidence {escape(i["confidence"])}</span></div>'
            f'<div class="issue-title">{escape(i["title"])}</div><div class="issue-action">{escape(i["text"])}</div>'
            + (f'<div class="muted small mono">' + " · ".join(f'{escape(e["key"])} = {escape(e["value"])}'
                                                             for e in i["evidence"]) + "</div>" if i["evidence"] else "")
            + "</li>" for i in items)
        groups.append(f'<h3>{heading} ({len(items)})</h3>' + (f'<ul class="requests">{cards}</ul>' if items
                                                              else '<p class="muted small">None.</p>'))
    note = ""
    if rejected:
        reasons = "".join(f"<li>{escape(r['title'] or '(untitled)')}: {escape('; '.join(r['reasons']))}</li>"
                          for r in rejected)
        note = (f'<details><summary>{len(rejected)} insight{"s" if len(rejected) != 1 else ""} rejected</summary>'
                f'<ul class="caveats">{reasons}</ul></details>')
    return f'<section class="card"><h2>AI analysis</h2>{intro}{"".join(groups)}{note}</section>'


ASK_SECTION = """<section class="card" id="ask" data-token="__ASK_TOKEN__"><h2>Ask about this data</h2>
<p class="ask-off muted small">To ask questions, run <code>python3 scripts/ask_server.py &lt;this folder&gt;</code> and open the
full address it prints (it includes a per-session token). Answers use only this dashboard's numbers; an answer citing
any other number is withheld.</p>
<form hidden><textarea rows="3" style="width:100%;font:inherit" placeholder="e.g. Which campaign drove the ROAS drop?"></textarea>
<p><button type="submit">Ask</button></p></form>
<div class="ask-answer" style="white-space:pre-wrap"></div><div class="ask-warn muted small"></div></section>"""


def facts_document(review: Review) -> dict:
    """facts.json: the engine's numbers under stable keys, plus rule findings and caveats."""
    return {"facts": build_facts(review), "actions": [a.as_dict() for a in review.actions],
            "caveats": review.ctx.caveats + review.log.warnings, "source": review.data.snapshot.path.name,
            "synthetic": review.data.snapshot.synthetic}


INSIGHTS_UNAVAILABLE = ('<section class="card"><h2>AI analysis</h2><p class="muted">The AI insights could not be used '
                        'or rendered ({}); run scripts/check_insights.py on the file. The Ask box below still works.</p></section>')


def build(review: Review, insights_path: Path | None) -> tuple[dict, str, str]:
    """(facts document, HTML for the AI analysis + Ask sections, Ask script).

    The insights file is outside input, so a problem with it only replaces the insights section: facts.json and the
    Ask box still work."""
    facts_doc = facts_document(review)
    # a bad insights file must not take facts.json or the Ask box with it
    insights_html = guarded("AI insights", lambda: ai_section(insights_path, facts_doc["facts"]),
                            lambda exc: INSIGHTS_UNAVAILABLE.format(escape(type(exc).__name__)))
    return facts_doc, f"{insights_html}\n{ASK_SECTION}", ASK_JS
