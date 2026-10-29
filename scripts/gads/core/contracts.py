"""What each query in queries/ must return: the canonical fields (config/field_map.json names) that the features
need. One source of truth for the reviews and for the first-connection check."""
from __future__ import annotations

QUERY_REQUIRED: dict[str, frozenset[str]] = {
    "account_activity": frozenset({"date", "impressions"}),
    "customer_settings": frozenset({"customer_id", "currency", "time_zone"}),
    "campaign_inventory": frozenset({"campaign_id", "campaign_status", "channel_type"}),
    "conversion_actions": frozenset({"conversion_action_id", "conversion_action_status"}),
    "campaign_daily": frozenset({"campaign_id", "date", "cost", "clicks"}),
    "search_terms": frozenset({"campaign_id", "search_term", "clicks", "cost"}),
    "keywords": frozenset({"campaign_id", "keyword_text", "match_type"}),
    "negative_keywords": frozenset({"campaign_id", "keyword_text", "match_type"}),
    "shared_negative_keywords": frozenset({"shared_set_id", "keyword_text", "match_type"}),
    "campaign_shared_sets": frozenset({"campaign_id", "shared_set_id"}),
    "campaign_share": frozenset({"campaign_id", "impression_share"}),
    "conversions_by_action": frozenset({"conversion_action_resource", "conversions", "all_conversions"}),
    "product_daily": frozenset({"item_id", "campaign_id", "date", "cost", "clicks"}),
}
