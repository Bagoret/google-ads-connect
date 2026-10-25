# Account map

> Structure of the Google Ads account(s). `UNKNOWN` = not yet supplied.
> Machine-readable campaign classification lives in `config/campaign_classification.json`.

## Accounts
| Field | Value | Source | As of |
|---|---|---|---|
| Customer ID(s) (format 123-456-7890) | UNKNOWN | | |
| Manager (MCC) account, if any | UNKNOWN | | |
| Account(s) in scope for analysis | UNKNOWN | | |
| Linked Merchant Center ID | UNKNOWN | | |
| Linked GA4 property | UNKNOWN | | |

## Campaign inventory
Fill from an MCP query (`queries/campaign_inventory.gaql`), not from memory. One row per campaign.

| Campaign ID | Campaign name | Type (Search / Shopping / PMax / Demand Gen / Display / Video) | Brand category (marketplace / stocked / generic / mixed) | Bid strategy | Status | Notes |
|---|---|---|---|---|---|---|
| UNKNOWN | | | | | | |

## Naming convention
| Field | Value |
|---|---|
| Convention in use (pattern) | UNKNOWN |
| Example names | UNKNOWN |
| Token meanings (e.g. `FR_SRCH_BRAND_...`) | UNKNOWN |
| Exceptions / legacy campaigns not following it | UNKNOWN |

## Structural notes
| Field | Value |
|---|---|
| Shared budgets in use | UNKNOWN |
| Shared negative keyword lists (names) | UNKNOWN |
| Account-level negative keywords | UNKNOWN |
| PMax brand exclusions configured | UNKNOWN |
| Feed labels / custom labels used for segmentation | UNKNOWN |
| Known overlaps (e.g. PMax and Shopping on same products) | UNKNOWN |
