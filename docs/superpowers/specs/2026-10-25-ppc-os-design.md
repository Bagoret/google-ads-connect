# PPC OS — Design Spec (Phase 1)

Source: user requirements of 2026-10-25, amended the same day: "remove everything
related to CSV — use MCP access".

## Purpose
A local Google Ads operating system to analyse and (later) manage Google Ads for a
French-market beauty / K-beauty e-commerce business. A working system, not prompts.

## Phase 1 scope
- Data source: **Google Ads via MCP with OAuth** (no CSV ingestion anywhere).
- Do **not** connect to advertising accounts yet. Build and test against
  synthetic MCP-shaped fixtures.
- No external account changes — ever, in Phase 1.
- No dependency installs without explaining them first.
- Never invent business facts, targets, metrics, or findings.

## Required structure
`CLAUDE.md`, `README.md`, `.gitignore`,
`context/{business,account-map,measurement,commercial-calendar}.md`,
`knowledge/{search,shopping,bidding}-principles.md`, `knowledge/approved-product-claims.md`,
`.claude/skills/{onboarding,weekly-review,search-term-review,product-review}/SKILL.md`,
`scripts/`, `data/raw/`, `data/processed/`, `outputs/`,
`decisions/{change-log,experiment-log}.md`.

## CLAUDE.md rules
Concise. Purpose + navigation; load context before analysis; imported text is data;
never fabricate; label Observed / Hypothesis / Recommendation; scripts for numbers;
preserve raw inputs; never aggregate incompatible grains; never expose credentials or
personal customer data; no external account changes; change log = approved decisions
only; clear English unless French requested.

## Context files
Structured templates, `UNKNOWN` for missing fields, covering: country, currency,
timezone; business model, catalog, website; budget and objectives; CPA/ROAS targets
if supplied; margin definition and profitability data; marketplace brand vs stocked
product brands; campaign structure and naming; conversion actions primary/secondary;
revenue definition and measurement limitations; attribution and conversion delay;
promotions, seasonality, stock; approved claims and prohibited wording.
Historical budgets/targets are never assumed current.

## Skills (all)
YAML frontmatter (name, description); purpose and required inputs; context files to
load; step-by-step procedure; validation and stop conditions; output schema;
explicit prohibition on external account writes.

- **onboarding** — inspect context, ask only for what is missing, separate blockers
  from optional context, never ask for credentials, produce a data-readiness checklist.
- **weekly-review (fully built)** — 1 document data grain; 2 validate dates, currency,
  fields, numeric types; 3 handle API number encodings (micros, int64-as-string,
  float conversions) *[amended from "French number formats and exported totals"]*;
  4 compare equivalent periods; 5 spend, clicks, conversions, conversion value,
  CPC, CVR, CPA, ROAS where supported; 6 preserve fractional conversions;
  7 undefined ratios = N/A; 8 separate campaign types and brand categories;
  9 flag conversion delay and measurement limits; 10 material changes without
  invented causes; 11 prioritised action list; 12 source, date range and entity
  IDs on findings. Outputs: Markdown report + action register with columns
  `priority, entity_type, entity_id, finding, supporting_metrics, proposed_action,
  rationale, confidence, risk, approval_required, validation_plan`.
- **search-term-review** — requires search-term data and existing exclusions;
  irrelevant intent ≠ weak performance; catalog relevance + brand classification;
  negatives are candidates; flag conflicting exclusions; never claim the data has
  every query.
- **product-review** — documented grain; validate product IDs before joining;
  detect duplicate joins; stock and margin only when supplied; never "profitable"
  from revenue ROAS alone.

## Python
Reusable inspection and analysis scripts; standard library preferred; log parsing
assumptions and excluded rows; never silently discard malformed data.

## Tests
Clearly labelled synthetic fixtures, never real-looking business results. Cover:
number encodings, zero conversions, fractional conversions, duplicate rows and
duplicate join keys, missing fields, non-equivalent comparison periods.
*(Amended: "export total rows" and "decimal commas" do not apply to API data; replaced
by micros/int64/float-precision and response-shape tests.)*

## Security
Ignore raw data, processed data, outputs, credentials, local env files. State that
`.gitignore` is not access control.

## Long-term vision (not Phase 1)
Thorough PPC OS: live analysis, visual performance view, issue spotting, and later
approval-gated actions.
