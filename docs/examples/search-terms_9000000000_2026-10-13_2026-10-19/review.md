# Search-term review — customer 9000000000 — 2026-10-13 to 2026-10-19

> **SYNTHETIC TEST DATA — NOT REAL.**

Source: `synthetic_search_terms.json` · Currency: EUR · 4 campaign × term rows · grain campaign_id × ad_group_id × search_term × matched_keyword_text × matched_keyword_match_type

> The search-terms data does not include every search query: Google withholds low-volume and privacy-thresholded queries, and Performance Max terms are not in this report.

## Data caveats

- conversion delay unknown (context/measurement.md): recent conversions and conversion value may still increase

## Terms (by cost)

Intent review is PENDING — weak performance is not the same as irrelevant intent.

| Campaign | Search term | Brand class | Clicks | Cost | Conv. | Weak-performance flag | Intent review |
|---|---|---|---|---|---|---|---|
| 9000000002 | synthbrand serum | stocked | 40 | 20.00 EUR | 2.5 | – | PENDING |
| 9000000002 | synthbrand sérum avis | stocked | 35 | 18.00 EUR | 0.0 | 0 conversions on 35 clicks (≥ 30) | PENDING |
| 9000000002 | synthshop crème | marketplace | 10 | 3.00 EUR | 1.0 | – | PENDING |
| 9000000002 | free serum sample | generic_or_unknown | 3 | 1.50 EUR | 0.0 | – | PENDING |

## Conflicting exclusions (approximate)

Negatives that would block an active keyword's own text. Close variants and accents are not modelled.

- campaign negative "serum" (PHRASE) blocks keyword "synthbrand serum" (PHRASE) — campaign 9000000002, keyword 7000000001

## Validation log

- shared negative keyword lists not supplied: conflict check covers campaign-level negatives only
