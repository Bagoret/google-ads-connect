# Shopping and Performance Max principles

> Analysis guidance, not account facts. Verify current product behaviour in
> official Google documentation before relying on any feature detail.

## Product data is the targeting
- In Shopping/PMax, the feed (titles, descriptions, product type, GTIN, brand,
  images, price, availability) determines which queries products match.
- Before blaming bids, check: disapprovals, limited visibility, price
  competitiveness, availability, missing GTINs, and title quality.

## Identifiers and joins
- Join performance to catalog on a single documented key (usually `item_id` /
  offer ID). Normalise case and whitespace before joining and log the rule.
- Check that the key is unique on the catalog side; duplicates multiply revenue.
- Item IDs returned by the Google Ads API (`segments.product_item_id`) may differ in
  case or format from the merchant's catalog IDs — confirm on real data before joining.

## Profitability
- Revenue ROAS is not profit. A product with high ROAS can lose money if margin
  is thin, returns are high, or discounts are deep.
- Only label a product "profitable" when margin/cost data is supplied, and
  state the margin definition used.
- Break-even ROAS = 1 / margin rate (margin as a share of conversion value,
  on the same VAT/shipping basis as the conversion value). Only compute when
  both definitions are known and compatible.

## Segmentation
- Segment by brand (stocked brands), category, price band, margin band (if
  supplied), and stock status (if supplied) — via custom labels where possible.
- Low-click products have unreliable ratios; report volume alongside ratios.

## PMax specifics to keep in mind
- PMax spend spans channels (Search, Shopping, Display, YouTube, …); a product
  report covers only the product-attributed portion. Do not add it to campaign
  totals from another query.
- PMax can capture marketplace-brand searches; check brand exclusions in
  `context/account-map.md` before comparing PMax to Search.
