# Search principles

> Working principles for analysis. They guide which questions to ask; they are
> not facts about this account. Google changes product behaviour often — verify
> current feature behaviour in official documentation before relying on it.

## Query intent first, performance second
- Judge **relevance** (does the query match something we sell and want to sell?)
  separately from **performance** (did it convert efficiently?).
- An irrelevant query is a negative candidate even with one click.
- A relevant query with weak results is a bid/landing-page/feed question, not
  automatically a negative. Low volume is not evidence of poor intent.

## Brand segmentation (see `context/business.md`)
- Keep marketplace-brand, stocked-brand, generic, and competitor-retailer traffic
  in separate reporting segments. Blended ROAS hides the mix.
- Marketplace-brand traffic usually has different economics (much of it might
  arrive anyway). Incrementality is a hypothesis to test, not an assumption.
- Stocked-brand queries (e.g. a K-beauty brand name + product) are core demand
  for a reseller; check brand-owner advertising restrictions before expanding.

## Match types and negatives
- Broad / phrase / exact behaviour depends on Google's current matching rules;
  close variants mean "exact" is not literal.
- Negative keywords do **not** match close variants the same way positives do;
  plurals, accents (e.g. "crème" vs "creme"), and misspellings may need listing.
- A negative can block a positive keyword: always check for conflicts.
- Search-terms reports do not show every query (low-volume/privacy thresholds).

## French-market specifics to check
- Accented and unaccented spellings, singular/plural, French and English product
  terms (e.g. "sérum" / "serum", "crème solaire" / "sunscreen").
- Korean brand romanisation variants and common misspellings.

## Diagnosis order for a performance change
1. Measurement (tracking changes, conversion action edits, consent changes).
2. Data comparability (date ranges, attribution lag, promotions, stock).
3. Spend/volume (budget limits, impression share, auction changes).
4. Efficiency (CPC, conversion rate, AOV/value per conversion).
Do not assign a cause without evidence from the data or the context files.
