---
name: onboarding
description: First-run setup for the Google Ads OS. Part 1 runs for every new person on a machine (owner, colleague, agency, freelancer, consultant, client); part 2 sets up the business context for a new business or while blockers remain. Use when the SessionStart hook reports a first run, when context has UNKNOWN blockers, or when the user asks what is still needed. Never asks for credentials and never changes any ad account.
---

# Onboarding

## Purpose
Get any person, for any business, from a fresh clone to "ready for a first weekly review", asking
only for what is missing.

- **Part 1 — person setup:** every new person, once per machine. Short.
- **Part 2 — business setup:** once per business, and again only while blockers remain.

## Hard rules
- **Never ask for credentials** — no tokens, client secrets, passwords, refresh tokens or credential
  files in chat or in repo files. Credentials are configured locally (`docs/mcp-setup.md`).
- **No external account writes.** Read-only MCP calls only (via `scripts/snapshot.py` and
  `scripts/check_connection.py`).
- Record only what the person states or what an MCP snapshot shows. Every business value gets a
  source (`stated by <relationship>` or `MCP snapshot <file>`) and an "as of" date. Never fill a field
  from assumptions, benchmarks, or the industry.
- Historical budgets or targets go in the "History" section, not the current tables.
- Ask in one grouped message per part. Every question can be skipped; UNKNOWN is acceptable.

## Context files
`local/profile.json` (part 1), `context/business.md`, `context/account-map.md`,
`context/measurement.md`, `context/commercial-calendar.md`, `knowledge/approved-product-claims.md`,
`config/campaign_classification.json`, `config/brand_lists.json` (part 2).

## Step 0 — where are we?
1. `python3 scripts/first_run.py --status`.
2. If `context_initialised` is false: `python3 scripts/init_workspace.py` (creates `context/` and the
   per-business config from `templates/`; never overwrites). This is a new business: run part 1, then part 2.
3. If `profile` is false: run part 1. If `business_blockers` > 0: offer part 2 after part 1.
4. Never run `init_workspace.py --reset` unless the user explicitly says this copy is for a different business.

## Part 1 — person setup (every new person)
1. Show, in 3–5 lines, what is already known about the business (from `context/business.md`:
   name, market, website, number of blockers), so the person sees what they are joining.
2. Ask, in one message:
   - Name or initials (optional, stays on this machine).
   - Relationship to the business: owner · employee · agency · freelancer · consultant · client · other.
   - Their Google Ads access level, if known: admin · standard · read_only · billing · email_only · none · unknown.
     Recommend **read_only** for analysis-only users (`docs/mcp-setup.md` › Adding other users).
   - What they will use it for: weekly-review · search-term-review · product-review · explore.
3. Save: `python3 scripts/first_run.py save --relationship … --access … --uses … [--name …]`.
   Reports, pages and replies are in English.
4. Connection: `python3 scripts/check_connection.py` (and `--live --customer-id <ID>` once configured).
   Relay FAIL/WARN lines and their fixes. If `.mcp.json` is missing, point to `docs/mcp-setup.md`
   (done on their own machine, with their own Google login).
5. Explain the ground rules in 3 bullets: read-only; every proposal needs approval; numbers come from scripts.

## Part 2 — business setup (new business, or blockers remain)
1. `python3 scripts/context_status.py`; read `outputs/onboarding/data-readiness.md`.
2. If the connection works, pull what the account can answer itself (read-only), instead of asking:
   - `scripts/snapshot.py --query customer_settings` → currency, timezone.
   - **Contract gate:** `scripts/inspect_snapshot.py <file>`. If it stops on an unknown shape, report it
     and stop: `scripts/gads/normalize.py` must be adapted before any analysis.
   - `campaign_inventory` and `conversion_actions` → draft the tables in `context/account-map.md` and
     `context/measurement.md` (source: MCP snapshot). Ask the person to confirm primary vs secondary meaning.
3. Ask one grouped message for what the account cannot answer:
   - **Blockers:** business / shop brand name and spellings; primary market; customer search language(s); stocked brands (and own-label, and brands that may not be advertised); Google Ads
     customer ID(s) in scope and any manager account; what conversion value includes (VAT, shipping,
     discounts, refunds).
   - **Optional:** industry / vertical; website and platform; other countries; budget and flexibility; objective; targets
     (with the date they were set); margin definition; conversion delay; competitor shops; promotions and
     stock constraints for the market; naming convention; approved claims and prohibited wording; who approves changes.
4. Adapt `context/commercial-calendar.md` candidate dates to the stated market (as candidates, not facts).
5. Write answers into the context files with source and date. If the person is not the owner or an
   employee, mark business facts "to confirm by the business" in the Source column.
6. Fill `config/brand_lists.json` and `config/campaign_classification.json` from confirmed answers only.
7. Re-run `python3 scripts/context_status.py`; report remaining blockers.

## Validation and stop conditions
- Stop if the person offers credentials: tell them not to share them and point to `docs/mcp-setup.md`.
- Stop the MCP steps on any `STOP:` from the scripts; report the reason.
- Do not mark a blocker resolved unless the value came from the person or a named snapshot.
- `first_run.py save` exits 2 on invalid values: ask again rather than guessing.

## Output schema
- Part 1: `local/profile.json` (`display_name, relationship, access, uses, first_run_completed_at`)
  and the connection check result.
- Part 2: updated `context/*.md` and `config/*.json` (confirmed values only) and
  `outputs/onboarding/data-readiness.md` (Blockers · Optional context · MCP and data checklist ·
  Analyses unlocked · Snapshots found).
- Reply: what was saved and from which source, blockers remaining (count + list), next recommended step.
