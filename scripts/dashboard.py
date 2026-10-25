#!/usr/bin/env python3
"""Local performance dashboard: one self-contained HTML file (no external scripts, fonts or
requests), built from a campaign_daily snapshot with the same engine as the weekly review.

Usage:
  python3 scripts/dashboard.py --snapshot data/raw/campaign_daily_<...>.json \
      --current 2026-10-13:2026-10-19 [--previous 2026-10-06:2026-10-12] [--expected-currency EUR] \
      [--conversion-lag-days N] [--target-roas X] [--target-cpa Y]

Writes outputs/dashboard_<customer>_<start>_<end>/index.html (gitignored). Open it in a browser.
Exit code 2 = analysis stopped (reason printed); nothing is written in that case.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.compare import pct_change  # noqa: E402
from gads.logbook import StopAnalysis  # noqa: E402
from gads.metrics import Totals, derive, fmt  # noqa: E402
from gads.normalize import unique_dir  # noqa: E402
from weekly_review import Review, build_parser, build_review  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ZERO = Decimal(0)

# KPI tiles: label, metric key, format, direction where "up" is good (+1), bad (-1) or neutral (0)
KPIS = [
    ("Cost", "cost", "money", 0),
    ("Conversions", "conversions", "conv", 1),
    ("Conversion value", "conversion_value", "money", 1),
    ("ROAS", "roas", "ratio", 1),
    ("CPA", "cpa", "money", -1),
    ("Conversion rate", "cvr", "pct", 1),
]
PRIORITY = {"P1": ("critical", "■", "Priority 1"), "P2": ("serious", "▲", "Priority 2"),
            "P3": ("warning", "●", "Priority 3")}


def _value(t: Totals, key: str):
    return getattr(t, key) if key in ("cost", "conversions", "conversion_value", "clicks") else derive(t)[key]


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def daily_series(review: Review) -> list[dict]:
    snap, ctx = review.data.snapshot, review.ctx
    by_day: dict[date, list[dict]] = {}
    for r in review.records:
        by_day.setdefault(r["date"], []).append(r)
    out = []
    for d in _days(snap.start, snap.end):
        rows = by_day.get(d, [])
        has_value = bool(rows) and all(r.get("conversion_value") is not None for r in rows)
        period = ("current" if ctx.current.contains(d) else
                  "previous" if ctx.previous and ctx.previous.contains(d) else "other")
        out.append({
            "date": d.isoformat(), "period": period, "rows": len(rows),
            "cost": str(sum((r.get("cost") or ZERO for r in rows), ZERO)),
            "conversion_value": str(sum((r["conversion_value"] for r in rows), ZERO)) if has_value else None,
            "clicks": sum(r.get("clicks") or 0 for r in rows),
        })
    return out


def campaign_sparks(review: Review) -> dict[str, list[Decimal]]:
    snap = review.data.snapshot
    index = {d: i for i, d in enumerate(_days(snap.start, snap.end))}
    sparks: dict[str, list[Decimal]] = {}
    for r in review.records:
        series = sparks.setdefault(r["campaign_id"], [ZERO] * len(index))
        series[index[r["date"]]] += r.get("cost") or ZERO
    return sparks


# ---------- SVG helpers ----------

def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    mag = 10 ** len(str(int(v))) / 10
    for step in (1, 2, 2.5, 5, 10):
        if step * mag >= v:
            return step * mag
    return 10 * mag


def _compact(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K".replace(".0K", "K")
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def _tick_indices(n: int, max_ticks: int = 7) -> list[int]:
    """Evenly spaced x ticks that always end on the last day without crowding the one before it."""
    step = max(1, -(-n // max_ticks))
    ticks = list(range(0, n, step))
    if ticks[-1] != n - 1:
        if n - 1 - ticks[-1] < step * 0.6:
            ticks[-1] = n - 1
        else:
            ticks.append(n - 1)
    return ticks


def line_chart(chart_id: str, daily: list[dict], key: str, currency: str) -> str:
    W, H, L, R, T, B = 560, 220, 44, 92, 16, 28
    pts = [(i, float(d[key])) for i, d in enumerate(daily) if d[key] is not None]
    if not pts:
        return '<p class="muted">No data for this metric.</p>'
    ymax = _nice_max(max(v for _, v in pts))
    n = max(len(daily) - 1, 1)
    x = lambda i: L + (W - L - R) * i / n  # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - v / ymax)  # noqa: E731
    parts = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Daily {escape(key.replace("_", " "))}" data-key="{key}">']
    cur = [i for i, d in enumerate(daily) if d["period"] == "current"]
    if cur:
        x0, x1 = x(cur[0]) - (W - L - R) / n / 2, x(cur[-1]) + (W - L - R) / n / 2
        x0, x1 = max(x0, L), min(x1, W - R)
        parts.append(f'<rect class="band" x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{H - T - B}"/>')
        parts.append(f'<text class="axis-label" x="{x0 + 4:.1f}" y="{T + 12}">Current period</text>')
    for k in range(5):
        v = ymax * k / 4
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        parts.append(f'<text class="tick" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{_compact(v)}</text>')
    for i in _tick_indices(len(daily)):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">'
                     f'{escape(daily[i]["date"][5:])}</text>')
    path, pen = [], "M"
    for i, d in enumerate(daily):
        if d[key] is None:
            pen = "M"
            continue
        path.append(f"{pen}{x(i):.1f},{y(float(d[key])):.1f}")
        pen = "L"
    area = (f'M{x(pts[0][0]):.1f},{y(0):.1f} ' + " ".join(f"L{x(i):.1f},{y(v):.1f}" for i, v in pts)
            + f' L{x(pts[-1][0]):.1f},{y(0):.1f} Z')
    parts.append(f'<path class="area" d="{area}"/>')
    parts.append(f'<path class="line" d="{" ".join(path)}"/>')
    li, lv = pts[-1]
    parts.append(f'<circle class="dot" cx="{x(li):.1f}" cy="{y(lv):.1f}" r="4"/>')
    label = fmt(Decimal(str(daily[li][key])), "money", currency)
    parts.append(f'<text class="end-label" x="{x(li) + 8:.1f}" y="{y(lv) + 4:.1f}">{escape(label)}</text>')
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{T}" y2="{H - B}" visibility="hidden"/>')
    parts.append(f'<rect class="hit" x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" '
                 f'data-n="{len(daily)}" data-l="{L}" data-w="{W - L - R}" tabindex="0"/>')
    parts.append("</svg>")
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def bar_chart(groups: dict[str, dict[str, Totals]], currency: str) -> str:
    rows = sorted(((name, g["current"].cost) for name, g in groups.items() if "current" in g), key=lambda r: -r[1])
    if not rows:
        return '<p class="muted">No data.</p>'
    W, L, R, BAR, GAP = 560, 156, 96, 20, 14
    H = len(rows) * (BAR + GAP) + 8
    top = float(max(v for _, v in rows)) or 1.0
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Current-period cost by segment">']
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
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def sparkline(values: list[Decimal], current_idx: set[int]) -> str:
    W, H = 96, 24
    top = float(max(values)) if values and max(values) > 0 else 1.0
    n = max(len(values) - 1, 1)
    pts = [(2 + (W - 4) * i / n, H - 2 - (H - 4) * float(v) / top) for i, v in enumerate(values)]
    base = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    cur = " ".join(f"{px:.1f},{py:.1f}" for i, (px, py) in enumerate(pts) if i in current_idx)
    return (f'<svg class="spark" viewBox="0 0 {W} {H}" aria-hidden="true">'
            f'<polyline class="spark-base" points="{base}"/>'
            + (f'<polyline class="spark-cur" points="{cur}"/>' if cur else "") + "</svg>")


# ---------- page sections ----------

def _delta_html(cur, prev, direction: int, ctx) -> str:
    if not ctx.previous:
        return '<span class="delta muted">no previous period</span>'
    if not ctx.equivalent:
        return '<span class="delta muted">not comparable</span>'
    change = pct_change(cur, prev)
    if change is None:
        return '<span class="delta muted">N/A</span>'
    arrow = "▲" if change > 0 else "▼" if change < 0 else "■"
    tone = "neutral" if direction == 0 or change == 0 else ("good" if (change > 0) == (direction > 0) else "bad")
    return f'<span class="delta {tone}">{arrow} {change:+.1f}%</span>'


def kpi_row(ctx) -> str:
    cur, prev = ctx.account["current"], ctx.account.get("previous")
    tiles = []
    for label, key, kind, direction in KPIS:
        v = _value(cur, key)
        pv = _value(prev, key) if prev else None
        tiles.append(
            f'<div class="tile"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{escape(fmt(v, kind, ctx.currency))}</div>'
            f'{_delta_html(v, pv, direction, ctx)}'
            + (f'<div class="tile-prev">prev. {escape(fmt(pv, kind, ctx.currency))}</div>' if prev else "")
            + "</div>")
    return '<section class="kpis" aria-label="Key metrics">' + "".join(tiles) + "</section>"


def campaign_table(review: Review, sparks: dict[str, list[Decimal]], daily: list[dict]) -> str:
    ctx = review.ctx
    cur_idx = {i for i, d in enumerate(daily) if d["period"] == "current"}
    rows = []
    for cid, totals in sorted(ctx.campaigns.items(), key=lambda kv: -kv[1]["current"].cost):
        meta, t = ctx.campaign_meta.get(cid, {}), totals["current"]
        d = derive(t)
        prev = totals.get("previous")
        delta = (_delta_html(t.cost, prev.cost, 0, ctx) if prev else '<span class="delta muted">new</span>')
        stopped = t.rows == 0 and prev is not None
        status = '<span class="badge warning">● Stopped</span>' if stopped else ""
        rows.append(
            f'<tr data-campaign="{escape(cid)}"><td class="mono">{escape(cid)}</td>'
            f'<td class="name">{escape(meta.get("name", ""))} {status}</td><td>{escape(meta.get("campaign_type", ""))}</td>'
            f'<td>{escape(meta.get("brand_category", ""))}</td>'
            f'<td class="num">{escape(fmt(t.cost, "money", ctx.currency))}</td><td>{delta}</td>'
            f'<td>{sparkline(sparks.get(cid, []), cur_idx)}</td>'
            f'<td class="num">{fmt(t.clicks, "count")}</td><td class="num">{fmt(t.conversions, "conv")}</td>'
            f'<td class="num">{escape(fmt(d["cpa"], "money", ctx.currency))}</td>'
            f'<td class="num">{fmt(d["roas"], "ratio")}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>ID</th><th>Campaign</th><th>Type</th><th>Brand</th>'
            '<th class="num">Cost</th><th>Δ cost</th><th>Daily cost</th><th class="num">Clicks</th>'
            '<th class="num">Conv.</th><th class="num">CPA</th><th class="num">ROAS</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")


def issues(actions) -> str:
    if not actions:
        return '<p class="muted">No rule fired for this period.</p>'
    items = []
    for a in actions:
        tone, icon, label = PRIORITY.get(a.priority, ("warning", "●", a.priority))
        items.append(
            f'<li class="issue"><span class="badge {tone}">{icon} {label}</span>'
            f'<div><div class="issue-title">{escape(a.entity_type)} {escape(a.entity_id)}: {escape(a.finding)}</div>'
            f'<div class="issue-action">Proposed: {escape(a.proposed_action)}</div>'
            f'<div class="muted small">Confidence {escape(a.confidence)} · Risk: {escape(a.risk)} · '
            f'Requires your approval</div></div></li>')
    return '<ul class="issues">' + "".join(items) + "</ul>"


def daily_table(daily: list[dict], currency: str) -> str:
    rows = "".join(
        f'<tr><td>{d["date"]}</td><td>{d["period"]}</td><td class="num">{fmt(Decimal(d["cost"]), "money", currency)}</td>'
        f'<td class="num">{fmt(Decimal(d["conversion_value"]), "money", currency) if d["conversion_value"] is not None else "N/A"}</td>'
        f'<td class="num">{d["clicks"]}</td></tr>' for d in daily)
    return ('<details><summary>Show data table</summary><div class="table-wrap"><table><thead><tr><th>Date</th>'
            '<th>Period</th><th class="num">Cost</th><th class="num">Conv. value</th><th class="num">Clicks</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div></details>')


def segment_table(groups: dict[str, dict[str, Totals]], currency: str) -> str:
    rows = "".join(
        f'<tr><td>{escape(name)}</td><td class="num">{fmt(g["current"].cost, "money", currency)}</td>'
        f'<td class="num">{fmt(g["current"].conversions, "conv")}</td>'
        f'<td class="num">{fmt(derive(g["current"])["roas"], "ratio")}</td></tr>'
        for name, g in sorted(groups.items()) if "current" in g)
    return ('<details><summary>Show data table</summary><div class="table-wrap"><table><thead><tr><th>Segment</th>'
            '<th class="num">Cost</th><th class="num">Conv.</th><th class="num">ROAS</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></details>')


def _safe_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


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
.chart-wrap{overflow-x:auto}.chart{width:100%;min-width:440px;height:auto;display:block;overflow:visible}
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
.badge.critical{background:var(--critical);color:#fff}.badge.serious{background:var(--serious)}.badge.warning{background:var(--warning)}
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


def render_dashboard(review: Review, generated_at: datetime) -> str:
    ctx, data, log = review.ctx, review.data, review.log
    snap, cur = data.snapshot, ctx.currency
    daily = daily_series(review)
    sparks = campaign_sparks(review)
    period_line = f"Current {ctx.current}" + (f" · Previous {ctx.previous}" if ctx.previous else "")
    comparability = ("" if not ctx.previous or ctx.equivalent else
                     f'<div class="banner">Periods are not comparable ({escape("; ".join(data.equivalence_reasons))}). '
                     "Deltas are hidden.</div>")
    caveats = "".join(f"<li>{escape(c)}</li>" for c in ctx.caveats + log.warnings)
    payload = {"currency": cur, "daily": daily}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google Ads dashboard</title><style>{CSS}</style></head>
<body><main>
<h1>Google Ads dashboard</h1>
<div class="sub">Customer {escape(ctx.customer_id)} · {escape(period_line)} · {escape(cur)}</div>
{'<div class="banner"><strong>SYNTHETIC TEST DATA — NOT REAL.</strong> Generated from a labelled test fixture.</div>' if snap.synthetic else ''}
{comparability}
{kpi_row(ctx)}
<div class="grid2">
<section class="card"><h2>Daily cost</h2>{line_chart("chart-cost", daily, "cost", cur)}{daily_table(daily, cur)}</section>
<section class="card"><h2>Daily conversion value</h2>{line_chart("chart-value", daily, "conversion_value", cur)}
<p class="muted small">Recent days may still gain conversions (conversion delay).</p></section>
</div>
<div class="grid2">
<section class="card"><h2>Cost by campaign type (current period)</h2>{bar_chart(data.by_type, cur)}{segment_table(data.by_type, cur)}</section>
<section class="card"><h2>Cost by brand category (current period)</h2>{bar_chart(data.by_brand, cur)}{segment_table(data.by_brand, cur)}
<p class="muted small">Categories come from config/campaign_classification.json; "unclassified" = not mapped yet.</p></section>
</div>
<section class="card"><h2>Issues to review</h2>
<p class="muted small">Rule-based findings. Each is a proposal; nothing changes in the account without your approval.</p>
{issues(review.actions)}</section>
<section class="card"><h2>Campaigns</h2>{campaign_table(review, sparks, daily)}</section>
<section class="card"><h2>Data caveats</h2><ul class="caveats">{caveats or '<li>None detected.</li>'}</ul></section>
<p class="muted small">Source: {escape(snap.path.name)} (fetched {escape(snap.fetched_at)}) · grain {escape(" × ".join(data.grain))} ·
{data.rows} rows · {len(log.excluded)} excluded · generated {escape(generated_at.isoformat(timespec="seconds"))} ·
thresholds from config/review_thresholds.json (not business-validated unless you set them)</p>
</main>
<script type="application/json" id="dash-data">{_safe_json(payload)}</script>
<script>{JS}</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        review = build_review(args)
    except StopAnalysis as exc:
        print(f"STOP: {exc.reason}", file=sys.stderr)
        return 2
    html = render_dashboard(review, datetime.now(timezone.utc))
    out = unique_dir(args.out, f"dashboard_{review.ctx.customer_id}_{review.ctx.current.start}_{review.ctx.current.end}")
    (out / "index.html").write_text(html, encoding="utf-8")
    print(out / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
