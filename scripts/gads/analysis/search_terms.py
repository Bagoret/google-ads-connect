"""Search-term review computation: brand classification, weak-performance flags, and conflicts between negative
keywords and active keywords. Intent judgement is left to the search-term-review skill (Claude + human); nothing
here labels a term "irrelevant". Rendering lives in gads.present.search_terms_page."""
from __future__ import annotations

import re
from decimal import Decimal
import unicodedata
from dataclasses import dataclass
from typing import Literal

from gads.analysis.config import load_thresholds
from gads.core.cli import load_json_file
from gads.core.logbook import RunLog, StopAnalysis
from gads.core.metrics import group_by
from gads.core.normalize import Snapshot, records_from_snapshot
from gads.core.validate import account_timezone, check_single_currency, check_unique, parse_now, partial_data_caveats

COVERAGE_NOTE = ("The search-terms data does not include every search query: Google withholds low-volume "
                 "and privacy-thresholded queries, and Performance Max terms are not in this report.")


def normalize_term(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _tokens(text: str) -> list[str]:
    text = re.sub(r'[\[\]"+]', " ", text)
    return text.casefold().split()


def classify_brand(term: str, lists: dict[str, list[str]]) -> Literal["marketplace", "stocked", "competitor", "generic_or_unknown"]:
    padded = f" {normalize_term(term)} "
    for label in ("marketplace", "stocked", "competitor"):
        for name in lists.get(label, []):
            if name and f" {normalize_term(name)} " in padded:
                return label
    return "generic_or_unknown"


def negative_blocks(neg_text: str, neg_match: Literal["EXACT", "PHRASE", "BROAD"], kw_text: str) -> bool:
    """Approximate: would this negative block the keyword's own text as a query?
    Case-insensitive; accents, plurals and other close variants are NOT modelled."""
    neg, kw = _tokens(neg_text), _tokens(kw_text)
    if not neg:
        return False
    if neg_match == "EXACT":
        return neg == kw
    if neg_match == "PHRASE":
        return any(kw[i:i + len(neg)] == neg for i in range(len(kw) - len(neg) + 1))
    if neg_match == "BROAD":
        return set(neg) <= set(kw)
    raise ValueError(f"unknown match type {neg_match}")


def active_keywords(kw_records: list[dict]) -> list[dict]:
    """Positive keywords that can serve: negatives and explicitly PAUSED keywords are left out."""
    return [k for k in kw_records if k.get("negative") != "true" and k.get("criterion_status") != "PAUSED"]


def find_conflicts(negatives: list[dict], keywords: list[dict]) -> list[dict]:
    conflicts = []
    by_campaign: dict[str, list[int]] = {}
    for i, kw in enumerate(keywords):
        by_campaign.setdefault(kw["campaign_id"], []).append(i)
    for neg in negatives:
        scope = set(neg.get("scope_campaign_ids") or [])
        for kw in (keywords[i] for i in sorted(i for cid in scope for i in by_campaign.get(cid, []))):
            if neg.get("ad_group_id") and neg["ad_group_id"] != kw.get("ad_group_id"):
                continue
            if negative_blocks(neg["keyword_text"], neg["match_type"], kw["keyword_text"]):
                conflicts.append({
                    "negative_text": neg["keyword_text"], "negative_match_type": neg["match_type"],
                    "negative_level": neg["level"], "negative_criterion_id": neg.get("criterion_id", ""),
                    "shared_set_id": neg.get("shared_set_id", ""),
                    "keyword_text": kw["keyword_text"], "keyword_match_type": kw["match_type"],
                    "keyword_criterion_id": kw.get("criterion_id", ""), "campaign_id": kw["campaign_id"],
                    "ad_group_id": kw.get("ad_group_id", ""),
                })
    return conflicts


def weak_performance(records: list[dict], thresholds: dict) -> list[dict]:
    min_clicks = thresholds["min_clicks_for_ratio"]
    min_spend = thresholds.get("min_spend_zero_conv")
    flags = []
    for r in records:
        if r.get("conversions") is None or r["conversions"] != 0:
            continue
        reasons = []
        if r["clicks"] >= min_clicks:
            reasons.append(f"0 conversions on {r['clicks']} clicks (≥ {min_clicks})")
        if min_spend is not None and r["cost"] >= Decimal(str(min_spend)):
            reasons.append(f"0 conversions on spend ≥ {min_spend}")
        if reasons:
            flags.append({"search_term": r["search_term"], "campaign_id": r["campaign_id"], "clicks": r["clicks"],
                          "cost": str(r["cost"]), "conversions": str(r["conversions"]), "flag": "; ".join(reasons)})
    return flags


def _negatives(args, log: RunLog) -> list[dict]:
    _, camp = records_from_snapshot(args.negatives, {"campaign_id", "keyword_text", "match_type"}, log, "negative_keywords")
    negs = [{**r, "level": "campaign", "scope_campaign_ids": [r["campaign_id"]]} for r in camp]
    if args.shared_negatives:
        if not args.campaign_shared_sets:
            raise StopAnalysis("--shared-negatives needs --campaign-shared-sets to know which campaigns they apply to")
        _, shared = records_from_snapshot(args.shared_negatives, {"shared_set_id", "keyword_text", "match_type"},
                                          log, "shared_negative_keywords")
        _, links = records_from_snapshot(args.campaign_shared_sets, {"campaign_id", "shared_set_id"},
                                         log, "campaign_shared_sets")
        linked: dict[str, list[str]] = {}
        for link in links:
            if link.get("shared_set_link_status", "ENABLED") == "ENABLED":
                linked.setdefault(link["shared_set_id"], []).append(link["campaign_id"])
        negs += [{**r, "level": "shared_set", "scope_campaign_ids": linked.get(r["shared_set_id"], [])} for r in shared]
    else:
        log.warn("shared negative keyword lists not supplied: conflict check covers campaign-level negatives only")
    return negs


@dataclass
class SearchTermReview:
    snap: Snapshot
    currency: str
    caveats: list[str]
    grain: tuple[str, ...]
    rows: list[dict]
    conflicts: list[dict]
    log: RunLog


def analyse(args) -> SearchTermReview:
    """args: the search-term review's options (--search-terms, --keywords, --negatives, … as attributes)."""
    if not args.negatives:
        raise StopAnalysis("existing exclusions are required: pass --negatives (negative_keywords snapshot)")
    if not args.keywords:
        raise StopAnalysis("active keywords are required: pass --keywords (keywords snapshot)")
    log = RunLog()
    snap, terms = records_from_snapshot(args.search_terms, {"campaign_id", "search_term", "clicks", "cost"},
                                        log, "search_terms", dated=True)
    grain = ("campaign_id", "ad_group_id", "search_term", "matched_keyword_text", "matched_keyword_match_type")
    check_unique(terms, grain)
    currency = check_single_currency(terms, args.expected_currency)
    caveats = partial_data_caveats(snap.end, account_timezone(terms, args.timezone), args.conversion_lag_days,
                                   parse_now(args.now))
    _, kw_records = records_from_snapshot(args.keywords, {"campaign_id", "keyword_text", "match_type"}, log, "keywords")
    keywords = active_keywords(kw_records)
    ad_group_negs = [{**k, "level": "ad_group", "scope_campaign_ids": [k["campaign_id"]]}
                     for k in kw_records if k.get("negative") == "true"]
    negatives = _negatives(args, log) + ad_group_negs
    lists = load_json_file(args.brand_lists, "brand lists")
    if not any(lists.get(k) for k in ("marketplace", "stocked", "competitor")):
        log.warn("brand lists are empty: every term is classified generic_or_unknown")
    thresholds = load_thresholds()

    per_term = []
    for key, t in group_by([{**r, "_k": f"{r['campaign_id']}\x1f{r['search_term']}"} for r in terms], "_k").items():
        cid, term = key.split("\x1f")
        per_term.append({"campaign_id": cid, "search_term": term, "clicks": t.clicks, "cost": t.cost,
                         "conversions": t.conversions, "conversion_value": t.conversion_value})
    weak = {(w["campaign_id"], w["search_term"]): w["flag"] for w in weak_performance(per_term, thresholds)}
    rows = [{
        "campaign_id": r["campaign_id"], "search_term": r["search_term"],
        "brand_class": classify_brand(r["search_term"], lists),
        "clicks": r["clicks"], "cost": str(r["cost"]),
        "conversions": None if r["conversions"] is None else str(r["conversions"]),
        "weak_performance": weak.get((r["campaign_id"], r["search_term"]), ""),
        "intent_review": "PENDING",
    } for r in sorted(per_term, key=lambda r: -r["cost"])]
    conflicts = find_conflicts(negatives, keywords)
    return SearchTermReview(snap, currency, caveats, grain, rows, conflicts, log)
