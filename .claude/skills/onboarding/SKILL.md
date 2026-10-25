---
name: onboarding
description: Set up or refresh the business context and data readiness for the Google Ads OS. Use at first run, when context files contain UNKNOWN fields that block an analysis, or when the user asks what is still needed. Asks only for missing information, never for credentials, and never changes any ad account.
---

# Onboarding

## Purpose
Get the system from empty templates to "ready for a first weekly review" by finding what is
missing, asking only for that, and producing a data-readiness checklist.

## Hard rules
- **Never ask for credentials** — no tokens, client secrets, passwords, or refresh tokens in chat or
  in repo files. Credentials are configured by the user locally (`docs/mcp-setup.md`).
- **No external account writes.** Read-only MCP calls only (`list_accessible_customers`, `search`
  via `scripts/snapshot.py`, `get_resource_metadata`).
- Record only what the user states or what an MCP snapshot shows; every value gets a source and an
  "as of" date. Never fill a field from assumptions or benchmarks.
- Historical budgets or targets go in the "History" section, not the current tables.

## Required inputs
None to start. The skill discovers what is missing.

## Context files
`context/business.md`, `context/account-map.md`, `context/measurement.md`,
`context/commercial-calendar.md`, `knowledge/approved-product-claims.md`,
`config/campaign_classification.json`, `config/brand_lists.json`.

## Procedure
1. Run `python3 scripts/context_status.py`. Read `outputs/onboarding/data-readiness.md`.
2. Check MCP readiness:
   - `.mcp.json` missing → point the user to `docs/mcp-setup.md` (they do it on their machine), stop the MCP part.
   - Present → call `list_accessible_customers`; confirm with the user which customer ID is in scope.
3. Pull facts the account can answer itself (read-only), instead of asking:
   - `python3 scripts/snapshot.py --query customer_settings --customer-id <ID>` → currency, timezone.
   - **Contract gate:** `python3 scripts/inspect_snapshot.py <file>`. If it stops on an unknown shape,
     report the shape and stop — `scripts/gads/normalize.py` must be adapted before any analysis.
   - `campaign_inventory` and `conversion_actions` snapshots → draft the campaign table in
     `context/account-map.md` and the conversion table in `context/measurement.md`, marked
     "source: MCP snapshot <file>". Ask the user to confirm primary vs secondary meaning and the revenue definition.
4. Ask the user **one grouped message** for the remaining blockers, then optional items:
   - Blockers: marketplace brand name, stocked brands list, accounts in scope, conversion value definition
     (anything not answerable from snapshots).
   - Optional: targets (with "as of" date), margin definition, conversion delay, promotions calendar,
     stock constraints, approved claims, prohibited wording.
   Make it clear optional items can be skipped; UNKNOWN is an acceptable answer.
5. Write answers into the context files (value + source + as-of). Fill `config/brand_lists.json` and
   `config/campaign_classification.json` from confirmed answers only.
6. Re-run `python3 scripts/context_status.py` and report remaining blockers.

## Validation and stop conditions
- Stop if the user offers credentials: tell them not to share them and to use `docs/mcp-setup.md`.
- Stop the MCP steps on any `STOP:` from the scripts; report the reason.
- Do not mark a blocker resolved unless the value came from the user or a named snapshot.

## Output schema
- Updated `context/*.md` and `config/*.json` (only confirmed values).
- `outputs/onboarding/data-readiness.md` with sections: Blockers · Optional context ·
  MCP and data checklist · Analyses unlocked · Snapshots found.
- Reply: blockers remaining (count + list), what was filled and from which source, next recommended step.
