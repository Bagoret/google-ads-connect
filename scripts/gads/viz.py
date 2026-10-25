"""Shared pieces for the local HTML pages: theme tokens, tooltip script, bar chart, badges.
Everything is inline; pages make no network requests. All data text is escaped by callers or here."""
from __future__ import annotations

import json
from decimal import Decimal
from html import escape

from .metrics import fmt


def safe_json(obj) -> str:
    """JSON that cannot close a <script> element."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def fold_top(rows: list[tuple[str, Decimal]], n: int = 8) -> list[tuple[str, Decimal]]:
    """Largest first; past n-1 entries the tail folds into one "Other (k)" bar (never a 9th hue or bar)."""
    rows = sorted(rows, key=lambda r: -r[1])
    if len(rows) <= n:
        return rows
    head, tail = rows[:n - 1], rows[n - 1:]
    return head + [(f"Other ({len(tail)})", sum((v for _, v in tail), Decimal(0)))]


def badge(tone: str, icon: str, text: str) -> str:
    return f'<span class="badge {tone}">{icon} {escape(text)}</span>'


def tile(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="tile"><div class="tile-label">{escape(label)}</div>'
            f'<div class="tile-value">{escape(value)}</div>'
            + (f'<div class="tile-prev">{escape(sub)}</div>' if sub else "") + "</div>")


def bar_chart(rows: list[tuple[str, Decimal]], currency: str, aria_label: str, table: bool = False) -> str:
    rows = sorted(rows, key=lambda r: -r[1])
    if not rows:
        return '<p class="muted">No data.</p>'
    W, L, R, BAR, GAP = 560, 156, 96, 20, 14
    H = len(rows) * (BAR + GAP) + 8
    top = float(max(v for _, v in rows)) or 1.0
    parts = [f'<svg class="chart bars" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(aria_label)}">']
    for k, (name, v) in enumerate(rows):
        y0 = 4 + k * (BAR + GAP)
        w = max((W - L - R) * float(v) / top, 0)
        r = min(4, w)
        d = (f"M{L},{y0} h{max(w - r, 0):.1f} a{r},{r} 0 0 1 {r},{r} v{BAR - 2 * r} "
             f"a{r},{r} 0 0 1 -{r},{r} h-{max(w - r, 0):.1f} Z") if w > 0 else ""
        tip = escape(f"{name}: {fmt(v, 'money', currency)}")
        parts.append(f'<text class="cat" x="{L - 8}" y="{y0 + BAR / 2 + 4}" text-anchor="end">{escape(name)}</text>')
        if d:
            parts.append(f'<path class="bar" d="{d}" data-tip="{tip}" tabindex="0"/>')
        parts.append(f'<text class="value" x="{L + w + 6:.1f}" y="{y0 + BAR / 2 + 4}">'
                     f'{escape(fmt(v, "money", currency))}</text>')
    parts.append(f'<line class="axis" x1="{L}" x2="{L}" y1="0" y2="{H}"/></svg>')
    html = '<div class="chart-wrap">' + "".join(parts) + "</div>"
    if table:
        body = "".join(f'<tr><td>{escape(name)}</td><td class="num">{escape(fmt(v, "money", currency))}</td></tr>'
                       for name, v in rows)
        html += ('<details><summary>Show data table</summary><div class="table-wrap"><table><thead><tr>'
                 f'<th>Segment</th><th class="num">Cost</th></tr></thead><tbody>{body}</tbody></table></div></details>')
    return html


def page(title: str, subtitle: str, synthetic: bool, body: str, footer: str, payload: dict | None = None) -> str:
    banner = ('<div class="banner"><strong>SYNTHETIC TEST DATA — NOT REAL.</strong> Generated from a labelled '
              'test fixture.</div>' if synthetic else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{escape(title)}</h1>
<div class="sub">{escape(subtitle)}</div>
{banner}
{body}
<p class="muted small">{footer}</p>
</main>
<script type="application/json" id="dash-data">{safe_json(payload or {})}</script>
<script>{JS}</script>
</body></html>
"""


CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--series:#2a78d6;--band:rgba(42,120,214,.06);--border:rgba(11,11,11,.10);
--good:#006300;--bad:#d03b3b;--critical:#d03b3b;--serious:#ec835a;--warning:#fab219}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#f0efec;--ink-2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--series:#3987e5;--band:rgba(57,135,229,.10);
--border:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink-2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--series:#3987e5;--band:rgba(57,135,229,.10);--border:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 12px}
.sub,.muted{color:var(--ink-2)}.small{font-size:12px}.mono{font-variant-numeric:tabular-nums}
.banner{border:1px solid var(--warning);background:var(--surface);padding:8px 12px;border-radius:8px;margin:12px 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-top:16px;min-width:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.tile-label{color:var(--ink-2);font-size:13px}.tile-value{font-size:24px;font-weight:600;margin:2px 0}
.tile-prev{color:var(--muted);font-size:12px}
.delta{font-size:13px;font-weight:600}.delta.good{color:var(--good)}.delta.bad{color:var(--bad)}
.delta.neutral{color:var(--ink-2)}.delta.muted{color:var(--muted);font-weight:400}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.chart-wrap{overflow-x:auto}.chart.bars{max-width:640px}.chart{width:100%;min-width:440px;height:auto;display:block;overflow:visible}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .tick,.chart .axis-label{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.chart .cat,.chart .value,.chart .end-label{fill:var(--ink-2);font-size:13px}
.chart .band{fill:var(--band)}.chart .line{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .area{fill:var(--series);opacity:.10}.chart .dot{fill:var(--series);stroke:var(--surface);stroke-width:2}
.chart .bar{fill:var(--series)}.chart .bar:hover,.chart .bar:focus{opacity:.8;outline:none}
.chart .crosshair{stroke:var(--axis);stroke-width:1}.chart .hit{fill:transparent;outline:none}
.spark{width:80px;height:24px}.spark-base{fill:none;stroke:var(--muted);stroke-width:1.5}
.spark-cur{fill:none;stroke:var(--series);stroke-width:2}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 6px;border-bottom:1px solid var(--grid);text-align:left;white-space:nowrap}td.name{white-space:normal;min-width:140px}
th{color:var(--ink-2);font-weight:600}.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;color:#0b0b0b;white-space:nowrap}
.badge.neutral{background:var(--grid);color:var(--ink)}.badge.critical{background:var(--critical);color:#fff}.badge.serious{background:var(--serious)}.badge.warning{background:var(--warning)}
.issues{list-style:none;margin:0;padding:0}.issue{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--grid)}
.issue-title{font-weight:600}.issue-action{color:var(--ink-2)}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink-2);font-size:13px}
.tooltip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:10}
.tooltip strong{display:block;font-size:14px}
ul.caveats{margin:0;padding-left:18px}
"""

JS = """
(function(){
  var data = JSON.parse(document.getElementById('dash-data').textContent);
  var tip = document.createElement('div'); tip.className = 'tooltip'; document.body.appendChild(tip);
  function show(x, y, value, label){
    tip.textContent = '';
    var s = document.createElement('strong'); s.textContent = value; tip.appendChild(s);
    tip.appendChild(document.createTextNode(label));
    tip.style.display = 'block';
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(4, Math.min(x + 14, window.innerWidth - w - 4)) + 'px';
    tip.style.top = Math.max(4, Math.min(y + 14, window.innerHeight - h - 4)) + 'px';
  }
  function hide(){ tip.style.display = 'none'; }
  document.querySelectorAll('svg.chart[data-key]').forEach(function(svg){
    var key = svg.getAttribute('data-key'), hit = svg.querySelector('.hit'), cross = svg.querySelector('.crosshair');
    var n = +hit.getAttribute('data-n'), l = +hit.getAttribute('data-l'), w = +hit.getAttribute('data-w');
    function at(clientX){
      var pt = svg.createSVGPoint(); pt.x = clientX; pt.y = 0;
      var x = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
      return Math.max(0, Math.min(n - 1, Math.round((x - l) / w * (n - 1))));
    }
    function move(i, cx, cy){
      var d = data.daily[i], xv = l + w * i / Math.max(n - 1, 1);
      cross.setAttribute('x1', xv); cross.setAttribute('x2', xv); cross.setAttribute('visibility', 'visible');
      var v = d[key] === null ? 'N/A' : Number(d[key]).toFixed(2) + ' ' + data.currency;
      show(cx, cy, v, d.date + ' · ' + d.period + ' period');
    }
    hit.addEventListener('pointermove', function(e){ move(at(e.clientX), e.clientX, e.clientY); });
    hit.addEventListener('pointerleave', function(){ cross.setAttribute('visibility', 'hidden'); hide(); });
    var idx = n - 1;
    hit.addEventListener('focus', function(){ var r = hit.getBoundingClientRect(); move(idx, r.left + r.width / 2, r.top); });
    hit.addEventListener('blur', function(){ cross.setAttribute('visibility', 'hidden'); hide(); });
    hit.addEventListener('keydown', function(e){
      if (e.key === 'ArrowLeft') idx = Math.max(0, idx - 1); else if (e.key === 'ArrowRight') idx = Math.min(n - 1, idx + 1); else return;
      var r = hit.getBoundingClientRect(); move(idx, r.left + r.width * idx / Math.max(n - 1, 1), r.top); e.preventDefault();
    });
  });
  document.querySelectorAll('.bar[data-tip]').forEach(function(bar){
    function on(e){ var r = bar.getBoundingClientRect(); var t = bar.getAttribute('data-tip').split(': ');
      show(e.clientX || r.right, e.clientY || r.top, t.slice(1).join(': '), t[0]); }
    bar.addEventListener('pointermove', on); bar.addEventListener('focus', on);
    bar.addEventListener('pointerleave', hide); bar.addEventListener('blur', hide);
  });
})();
"""


