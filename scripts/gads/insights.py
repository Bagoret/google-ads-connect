"""Facts (every number the engine computed, under stable keys) and verification of AI-written text.

AI text may cite numbers only as {{fact.key}} placeholders. render_text() substitutes real values and
reports unknown keys and any number typed by hand, so an insight can never carry a made-up figure.
Allowed bare numbers: entity IDs and the period dates that appear in the facts.
"""
from __future__ import annotations

import re

from .compare import pct_change
from .metrics import Totals, derive, fmt

METRICS = [("cost", "ratio"), ("impressions", "count"), ("clicks", "count"), ("conversions", "conv"),
           ("conversion_value", "ratio"), ("cpc", "ratio"), ("ctr", "pct"), ("cvr", "pct"), ("cpa", "ratio"),
           ("roas", "ratio")]
KINDS = {"issue", "opportunity"}
LABELS = {"Observed", "Hypothesis", "Recommendation"}
CONFIDENCE = {"low", "medium", "high"}
PLACEHOLDER = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")
NUMBER = re.compile(r"\d[\d.,:/\-]*%?")


def _metric(t: Totals, key: str):
    return getattr(t, key) if key in ("cost", "impressions", "clicks", "conversions", "conversion_value") \
        else derive(t)[key]


def _fmt(value, kind: str) -> str:
    return fmt(value, kind).replace(",", "") if kind == "count" else fmt(value, kind)


def _block(prefix: str, totals: dict[str, Totals], comparable: bool) -> dict[str, str]:
    out = {}
    for label in ("current", "previous"):
        if label in totals:
            for key, kind in METRICS:
                out[f"{prefix}.{label}.{key}"] = _fmt(_metric(totals[label], key), kind)
    if comparable and "previous" in totals:
        for key, _ in METRICS:
            change = pct_change(_metric(totals["current"], key), _metric(totals["previous"], key))
            out[f"{prefix}.delta.{key}"] = "N/A" if change is None else f"{change:+.1f}%"
    return out


def build_facts(review) -> dict[str, str]:
    ctx = review.ctx
    facts = {
        "meta.customer_id": ctx.customer_id,
        "meta.currency": ctx.currency,
        "meta.current_period": str(ctx.current),
        "meta.current_days": str(ctx.current.days),
        "meta.periods_comparable": "yes" if ctx.previous and ctx.equivalent else "no",
    }
    if ctx.previous:
        facts["meta.previous_period"] = str(ctx.previous)
    comparable = bool(ctx.previous and ctx.equivalent)
    facts.update(_block("account", ctx.account, comparable))
    for cid, totals in ctx.campaigns.items():
        meta = ctx.campaign_meta.get(cid, {})
        facts[f"campaign.{cid}.name"] = meta.get("name", "")
        facts[f"campaign.{cid}.type"] = meta.get("campaign_type", "")
        facts[f"campaign.{cid}.brand_category"] = meta.get("brand_category", "")
        facts.update(_block(f"campaign.{cid}", totals, comparable))
    return facts


def _allowed_numbers(facts: dict[str, str]) -> set[str]:
    allowed = {facts.get("meta.customer_id", "")}
    for key in facts:
        parts = key.split(".")
        if len(parts) > 2 and parts[1].isdigit():
            allowed.add(parts[1])
    for key in ("meta.current_period", "meta.previous_period"):
        allowed.update(re.findall(r"\d{4}-\d{2}-\d{2}", facts.get(key, "")))
    return allowed - {""}


def render_text(text: str, facts: dict[str, str]) -> tuple[str, list[str]]:
    problems = [f"unknown fact {{{{{k}}}}}" for k in PLACEHOLDER.findall(text) if k not in facts]
    allowed = _allowed_numbers(facts)
    for token in NUMBER.findall(PLACEHOLDER.sub("", text)):
        token = token.rstrip(".,:/-")
        if token and token not in allowed:
            problems.append(f"number not from facts: {token}")
    rendered = PLACEHOLDER.sub(lambda m: facts.get(m.group(1), m.group(0)), text)
    return rendered, problems


def validate_insights(data: dict, facts: dict[str, str]) -> tuple[list[dict], list[dict]]:
    ok, rejected = [], []
    allowed_ids = _allowed_numbers(facts) | {"account"}
    for i, item in enumerate((data or {}).get("insights", [])):
        reasons = []
        if not isinstance(item, dict):
            rejected.append({"index": i, "title": "", "reasons": ["not an object"]})
            continue
        if item.get("kind") not in KINDS:
            reasons.append(f"kind must be one of {sorted(KINDS)}")
        if item.get("label") not in LABELS:
            reasons.append(f"label must be one of {sorted(LABELS)}")
        if item.get("confidence") not in CONFIDENCE:
            reasons.append(f"confidence must be one of {sorted(CONFIDENCE)}")
        title, text = item.get("title"), item.get("text")
        if not (isinstance(title, str) and title.strip() and isinstance(text, str) and text.strip()):
            reasons.append("title and text are required")
            title, text = str(title or ""), str(text or "")
        evidence = item.get("evidence") or []
        if not isinstance(evidence, list) or any(not isinstance(e, str) for e in evidence):
            reasons.append("evidence must be a list of fact keys")
            evidence = []
        missing = [e for e in evidence if e not in facts]
        if missing:
            reasons.append(f"unknown evidence keys: {missing}")
        if item.get("label") in ("Observed", "Recommendation") and not evidence:
            reasons.append("Observed and Recommendation insights need at least one evidence key")
        entity_id = str(item.get("entity_id") or "")
        if entity_id and entity_id not in allowed_ids:
            reasons.append(f"unknown entity_id {entity_id}")
        rendered_title, p1 = render_text(title, facts)
        rendered_text, p2 = render_text(text, facts)
        reasons += p1 + p2
        if reasons:
            rejected.append({"index": i, "title": title, "reasons": reasons})
            continue
        ok.append({"kind": item["kind"], "label": item["label"], "confidence": item["confidence"],
                   "title": rendered_title, "text": rendered_text,
                   "entity_type": str(item.get("entity_type") or ""), "entity_id": entity_id,
                   "evidence": [{"key": e, "value": facts[e]} for e in evidence]})
    return ok, rejected
