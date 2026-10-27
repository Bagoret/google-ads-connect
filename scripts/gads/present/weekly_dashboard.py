"""Weekly dashboard page: KPI tiles, daily charts, segment mix, issues, campaigns. Pure rendering of a weekly
Review (gads.analysis.weekly); it never imports the AI component."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape

from gads.analysis.weekly import Review
from gads.core.compare import pct_change
from gads.core.metrics import Totals, derive, fmt
from gads.present.viz import bar_chart, caveats_card, page, source_note

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


def _current_costs(groups: dict[str, dict[str, Totals]]) -> list[tuple[str, Decimal]]:
    return [(name, g["current"].cost) for name, g in groups.items() if "current" in g]


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


def render_dashboard(review: Review, generated_at: datetime, ai_html: str = "", ai_js: str = "") -> str:
    """The weekly dashboard page. ai_html/ai_js are the AI analysis and Ask sections, built by the caller
    (gads.ai.dashboard_section) so a failure there can never stop this page from rendering."""
    ctx, data, log = review.ctx, review.data, review.log
    snap, cur = data.snapshot, ctx.currency
    daily = daily_series(review)
    sparks = campaign_sparks(review)
    period_line = f"Current {ctx.current}" + (f" · Previous {ctx.previous}" if ctx.previous else "")
    comparability = ("" if not ctx.previous or ctx.equivalent else
                     f'<div class="banner">Periods are not comparable ({escape("; ".join(data.equivalence_reasons))}). '
                     "Deltas are hidden.</div>")
    body = f"""{comparability}
{kpi_row(ctx)}
<div class="grid2">
<section class="card"><h2>Daily cost</h2>{line_chart("chart-cost", daily, "cost", cur)}{daily_table(daily, cur)}</section>
<section class="card"><h2>Daily conversion value</h2>{line_chart("chart-value", daily, "conversion_value", cur)}
<p class="muted small">Recent days may still gain conversions (conversion delay).</p></section>
</div>
<div class="grid2">
<section class="card"><h2>Cost by campaign type (current period)</h2>{bar_chart(_current_costs(data.by_type), cur, 'Current-period cost by campaign type')}{segment_table(data.by_type, cur)}</section>
<section class="card"><h2>Cost by brand category (current period)</h2>{bar_chart(_current_costs(data.by_brand), cur, 'Current-period cost by brand category')}{segment_table(data.by_brand, cur)}
<p class="muted small">Categories come from config/campaign_classification.json; "unclassified" = not mapped yet.</p></section>
</div>
<section class="card"><h2>Issues to review</h2>
<p class="muted small">Rule-based findings. Each is a proposal; nothing changes in the account without your approval.</p>
{issues(review.actions)}</section>
{ai_html}
<section class="card"><h2>Campaigns</h2>{campaign_table(review, sparks, daily)}</section>
{caveats_card(ctx.caveats + log.warnings)}"""
    footer = (f"{source_note(snap)} · grain {escape(' × '.join(data.grain))} ·\n"
              f"{data.rows} rows · {len(log.excluded)} excluded · generated {escape(generated_at.isoformat(timespec='seconds'))} ·\n"
              "thresholds from config/review_thresholds.json (not business-validated unless you set them)")
    return page("Google Ads dashboard", f"Customer {ctx.customer_id} · {period_line} · {cur}", snap.synthetic,
                body, footer, {"currency": cur, "daily": daily}, extra_js=ai_js)
