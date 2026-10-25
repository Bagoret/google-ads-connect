# Weekly review — customer 9000000000 — 2026-10-13 to 2026-10-19

> **SYNTHETIC TEST DATA — NOT REAL.** This report was generated from a labelled test fixture.

Statements are labelled **Observed** (from the named snapshot), **Hypothesis**, or **Recommendation**. All proposed actions require approval; nothing has been changed in any account.

## Sources & grain

- Snapshot: `synthetic_weekly_two_weeks.json` (query `campaign_daily`, fetched 2026-10-25T09:00:00+00:00)
- Customer ID: 9000000000 · Currency: EUR
- Requested range in snapshot: 2026-10-06 to 2026-10-19
- Grain: campaign_id × date · Rows used: 42 · Rows excluded: 0
- Current period: 2026-10-13 to 2026-10-19 · Previous period: 2026-10-06 to 2026-10-12

## Validation log

- No assumptions, warnings, or excluded rows.

## Comparison validity

Equivalent periods (7 days each, same weekday mix, no overlap). Deltas shown.

## Account totals

| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |
|---|---|---|---|---|---|---|---|---|---|---|
| Current (2026-10-13 to 2026-10-19) | 273.00 EUR | 11,900 | 595 | 12.81 | 507.50 EUR | 0.46 EUR | 5.00% | 2.15% | 21.31 EUR | 1.86 |
| Previous (2026-10-06 to 2026-10-12) | 238.00 EUR | 11,900 | 525 | 14.00 | 560.00 EUR | 0.45 EUR | 4.41% | 2.67% | 17.00 EUR | 2.35 |
| Δ % | +14.7% | +0.0% | +13.3% | -8.5% | -9.4% | +1.2% | +13.3% | -19.3% | +25.4% | -21.0% |

## By campaign type

**PERFORMANCE_MAX**

| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |
|---|---|---|---|---|---|---|---|---|---|---|
| Current (2026-10-13 to 2026-10-19) | 28.00 EUR | 2,100 | 35 | 0.00 | 0.00 EUR | 0.80 EUR | 1.67% | 0.00% | N/A | 0.00 |
| Previous (2026-10-06 to 2026-10-12) | 28.00 EUR | 2,100 | 35 | 0.00 | 0.00 EUR | 0.80 EUR | 1.67% | 0.00% | N/A | 0.00 |
| Δ % | +0.0% | +0.0% | +0.0% | N/A | N/A | +0.0% | +0.0% | N/A | N/A | N/A |

**SEARCH**

| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |
|---|---|---|---|---|---|---|---|---|---|---|
| Current (2026-10-13 to 2026-10-19) | 105.00 EUR | 2,800 | 210 | 2.31 | 87.50 EUR | 0.50 EUR | 7.50% | 1.10% | 45.45 EUR | 0.83 |
| Previous (2026-10-06 to 2026-10-12) | 70.00 EUR | 2,800 | 140 | 3.50 | 140.00 EUR | 0.50 EUR | 5.00% | 2.50% | 20.00 EUR | 2.00 |
| Δ % | +50.0% | +0.0% | +50.0% | -34.0% | -37.5% | +0.0% | +50.0% | -56.0% | +127.3% | -58.3% |

**SHOPPING**

| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |
|---|---|---|---|---|---|---|---|---|---|---|
| Current (2026-10-13 to 2026-10-19) | 140.00 EUR | 7,000 | 350 | 10.50 | 420.00 EUR | 0.40 EUR | 5.00% | 3.00% | 13.33 EUR | 3.00 |
| Previous (2026-10-06 to 2026-10-12) | 140.00 EUR | 7,000 | 350 | 10.50 | 420.00 EUR | 0.40 EUR | 5.00% | 3.00% | 13.33 EUR | 3.00 |
| Δ % | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% |

## By brand category

Brand categories come from `config/campaign_classification.json`; `unclassified` means not yet mapped.

**unclassified**

| Period | Cost | Impr. | Clicks | Conv. | Conv. value | CPC | CTR | CVR | CPA | ROAS |
|---|---|---|---|---|---|---|---|---|---|---|
| Current (2026-10-13 to 2026-10-19) | 273.00 EUR | 11,900 | 595 | 12.81 | 507.50 EUR | 0.46 EUR | 5.00% | 2.15% | 21.31 EUR | 1.86 |
| Previous (2026-10-06 to 2026-10-12) | 238.00 EUR | 11,900 | 525 | 14.00 | 560.00 EUR | 0.45 EUR | 4.41% | 2.67% | 17.00 EUR | 2.35 |
| Δ % | +14.7% | +0.0% | +13.3% | -8.5% | -9.4% | +1.2% | +13.3% | -19.3% | +25.4% | -21.0% |

## By campaign

| Campaign ID | Name (latest) | Type | Brand | Cost | Clicks | Conv. | CPA | ROAS | Δ cost |
|---|---|---|---|---|---|---|---|---|---|
| 9000000001 | SYNTH_Shopping_A | SHOPPING | unclassified | 140.00 EUR | 350 | 10.50 | 13.33 EUR | 3.00 | +0.0% |
| 9000000002 | SYNTH_Search_Renamed | SEARCH | unclassified | 105.00 EUR | 210 | 2.31 | 45.45 EUR | 0.83 | +50.0% |
| 9000000003 | SYNTH_PMax_C | PERFORMANCE_MAX | unclassified | 28.00 EUR | 35 | 0.00 | N/A | 0.00 | +0.0% |

## Observed material changes

- **Observed** [account 9000000000]: Material change vs 2026-10-06 to 2026-10-12: CPA +25.4%, ROAS -21.0%. Evidence: current 2026-10-13 to 2026-10-19: cost=273.00 EUR, clicks=595, conv=12.81, value=507.50 EUR, CPA=21.31 EUR, ROAS=1.86, CVR=2.15%; previous 2026-10-06 to 2026-10-12: cost=238.00 EUR, clicks=525, conv=14.00, value=560.00 EUR, CPA=17.00 EUR, ROAS=2.35, CVR=2.67%; source=synthetic_weekly_two_weeks.json
- **Observed** [campaign 9000000002]: Material change vs 2026-10-06 to 2026-10-12: cost +50.0%, CPA +127.3%, ROAS -58.3%, CVR -56.0%. Evidence: current 2026-10-13 to 2026-10-19: cost=105.00 EUR, clicks=210, conv=2.31, value=87.50 EUR, CPA=45.45 EUR, ROAS=0.83, CVR=1.10%; previous 2026-10-06 to 2026-10-12: cost=70.00 EUR, clicks=140, conv=3.50, value=140.00 EUR, CPA=20.00 EUR, ROAS=2.00, CVR=2.50%; source=synthetic_weekly_two_weeks.json

## Measurement caveats

- conversion delay unknown (context/measurement.md): recent conversions and conversion value may still increase
- The previous period's conversions have had longer to be attributed than the current period's.
- Conversion definitions, attribution model and revenue basis: see context/measurement.md (UNKNOWN fields there limit interpretation).

## Prioritised actions

Full register: `actions.json` / `actions.md`. Every item is a **Recommendation** requiring approval.

| # | Priority | Entity | Finding | Proposed action | Confidence |
|---|---|---|---|---|---|
| 1 | P2 | account 9000000000 | Material change vs 2026-10-06 to 2026-10-12: CPA +25.4%, ROAS -21.0% | Investigate drivers (change history, budget limits, auction metrics, promotions, stock, landing pages) before changing bids or budgets | medium |
| 2 | P2 | campaign 9000000002 | Material change vs 2026-10-06 to 2026-10-12: cost +50.0%, CPA +127.3%, ROAS -58.3%, CVR -56.0% | Investigate drivers (change history, budget limits, auction metrics, promotions, stock, landing pages) before changing bids or budgets | medium |

## Thresholds used

Analysis sensitivity parameters from `config/review_thresholds.json` — defaults, not business-validated unless you have set them.

- `min_clicks_for_ratio`: 30
- `material_pct_change`: 20
- `min_spend_zero_conv`: None
- `tracking_drop_pct`: 50
- `tracking_click_stability_pct`: 20
- No targets supplied.

## What this report cannot tell you

- Why a metric changed. Changes are observed; causes need change history, auction data, site and stock checks.
- Incrementality — whether conversions (especially marketplace-brand) would have happened without ads.
- Profit. Conversion value is revenue as defined in context/measurement.md, not margin.
- Every search query, or Performance Max channel/asset splits — those need separate queries.
- Anything that happened after the snapshot was fetched.
