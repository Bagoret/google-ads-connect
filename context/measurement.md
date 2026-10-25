# Measurement

> How conversions and revenue are measured. `UNKNOWN` = not yet supplied.
> Every report must state which conversion definition its numbers use.

## Conversion actions
| Conversion action | Source (Google Ads tag / GA4 import / offline / Shopify app) | Primary or secondary | Counting (every / one) | Value (dynamic / fixed / none) | Include in "Conversions" | Notes |
|---|---|---|---|---|---|---|
| UNKNOWN | | | | | | |

## Revenue definition
| Field | Value | Source | As of |
|---|---|---|---|
| Conversion value = (order total incl. VAT / excl. VAT / excl. shipping / …) | UNKNOWN | | |
| Includes shipping? | UNKNOWN | | |
| Includes VAT? | UNKNOWN | | |
| Discounts deducted? | UNKNOWN | | |
| Refunds / cancellations adjusted? | UNKNOWN | | |
| Back-end source of truth for revenue (platform, file) | UNKNOWN | | |

## Attribution and timing
| Field | Value | Source | As of |
|---|---|---|---|
| Attribution model (data-driven / last click / …) | UNKNOWN | | |
| Click-through conversion window | UNKNOWN | | |
| View-through / engaged-view windows | UNKNOWN | | |
| Typical conversion delay (days from click to conversion) | UNKNOWN | | |
| Days of recent data to treat as incomplete | UNKNOWN | | |
| Conversion date basis used in reports (interaction date vs conversion date) | UNKNOWN | | |

`weekly_review.py --conversion-lag-days N` should only be given a value that
appears in this table. If UNKNOWN, the report flags recent data as possibly
incomplete.

## Consent and data quality
| Field | Value | Source | As of |
|---|---|---|---|
| Consent banner / CMP in use | UNKNOWN | | |
| Consent Mode (none / basic / advanced) | UNKNOWN | | |
| Enhanced conversions enabled | UNKNOWN | | |
| Known tracking outages (dates) | UNKNOWN | | |
| Known duplicate-counting issues | UNKNOWN | | |
| Other known measurement limitations | UNKNOWN | | |

## Change history of measurement setup
| Date | Change | Impact on comparability |
|---|---|---|
