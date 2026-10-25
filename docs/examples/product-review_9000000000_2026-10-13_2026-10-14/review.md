# Product review — customer 9000000000 — 2026-10-13 to 2026-10-14

> **SYNTHETIC TEST DATA — NOT REAL.**

Source: `synthetic_product_daily.json` · Currency: EUR · Grain: item_id × period (from item_id × campaign_id × date) · 3 items

## Data caveats

- conversion delay unknown (context/measurement.md): recent conversions and conversion value may still increase

Margin definition (supplied): SYNTHETIC gross margin excl. VAT as a share of conversion value. `margin_after_ad_cost` = conversion value × margin rate − ad cost; it excludes returns, shipping and other costs unless the definition includes them.

| item_id | title | brand | cost | clicks | conversions | conversion_value | revenue_roas | cpa | margin_rate | estimated_margin | margin_after_ad_cost | stock_status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| synth-sku-001 | SYNTH product SYNTH-SKU-001 | SynthBrand | 16.00 | 40 | 2.00 | 80.00 | 5.00 | 8.00 | 0.40 | 32.00 | 16.00 | in_stock |
| synth-sku-002 | SYNTH product SYNTH-SKU-002 | SynthBrand | 10.00 | 20 | 1.00 | 20.00 | 2.00 | 10.00 | 0.10 | 2.00 | -8.00 | low_stock |
| synth-sku-003 | SYNTH product SYNTH-SKU-003 | OtherSynth | 4.00 | 10 | 0.00 | 0.00 | 0.00 | N/A | N/A | N/A | N/A | N/A |

## Join check

- Items with performance but no supplement row: 1 (synth-sku-003)
- Supplement items with no performance: 1 (synth-sku-999)

## Validation log

- Assumption: grain aggregated from item_id × campaign_id × date to item_id × period (all campaigns in this shopping_performance_view snapshot)
- Assumption: item IDs normalised with strip + casefold on both sides before joining
- Warning: 1 item(s) with performance but no supplement row
- Warning: 1 supplement item(s) with no performance in this period
