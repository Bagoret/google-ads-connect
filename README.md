# Google Ads Connect — a local PPC operating system

A local, evidence-first system for analysing (and later managing) Google Ads for a French-market
beauty / K-beauty e-commerce business. Claude Code runs the workflows; Python scripts do every
calculation; data comes from Google's official **read-only Google Ads MCP server** over OAuth.

**Status: Phase 1.** Read-only analysis engine, four skills, and the write-action groundwork are built
and tested on synthetic data. **No ad account is connected yet.**

## What it does
| Workflow | Skill | Script | Output |
|---|---|---|---|
| Fill business context, check readiness | `onboarding` | `scripts/context_status.py` | `outputs/onboarding/data-readiness.md` |
| Weekly performance review | `weekly-review` | `scripts/weekly_review.py` | report + action register |
| Search-term review | `search-term-review` | `scripts/search_terms.py` | review + negative candidates + conflicts |
| Product review | `product-review` | `scripts/product_review.py` | item table + join check |
| Check the OAuth/MCP connection | `onboarding` | `scripts/check_connection.py` | pass/fail checklist (no secrets printed) |
| Fetch data (read-only) | all | `scripts/snapshot.py`, `scripts/inspect_snapshot.py` | `data/raw/*.json` |

Sample output, generated from labelled synthetic data: [`docs/examples/`](docs/examples/).

## How data flows
```
queries/*.gaql ──► scripts/snapshot.py ──► data/raw/<snapshot>.json   (verbatim, never edited)
 (read-only GAQL)   (MCP stdio client,            │
                     read-only tool allowlist)    ▼
                     normalise → validate → metrics → compare → rules → report
                                                  │
                     outputs/<review>/report.md · actions.json · actions.md · run-log.json
```
Every analysis stops, rather than guessing, on: unknown response shape, paginated or partial
responses, missing required fields, duplicate keys, mixed currencies, unknown timezone, or
periods outside the data. Undefined ratios show `N/A`; fractional conversions stay exact.

## Structure
```
CLAUDE.md                 project rules for Claude (read first)
context/                  business facts — UNKNOWN until you supply them
knowledge/                PPC principles, approved claims
config/                   field map, thresholds, campaign classification, brand lists, execution kill switch
queries/                  versioned read-only GAQL
scripts/                  CLIs + scripts/gads/ engine (standard library only)
.claude/skills/           onboarding, weekly-review, search-term-review, product-review
.claude/settings.json     best-effort denies (GoMarble connector; Edit/Write tools on data/raw and the kill switch)
data/raw, data/processed  account data (gitignored)
outputs/                  reports (gitignored)
decisions/                change log (approved only), experiment log
docs/                     MCP setup, write path, plans, examples
tests/                    unittest suite + synthetic fixtures + fake MCP server
```

## Quick start
Requirements: Python ≥ 3.10. No packages to install for this repo.
```bash
python3 -m unittest discover -s tests          # run the test suite
python3 scripts/context_status.py               # what context is still missing
```

### Running onboarding (on your machine)
1. Connect the MCP server with OAuth: follow [`docs/mcp-setup.md`](docs/mcp-setup.md). You configure
   credentials locally; never paste them into chat. Check the setup with
   `python3 scripts/check_connection.py --live --customer-id <ID>`.
2. Open Claude Code in this folder and say **"run onboarding"**. Claude will:
   - list the missing context (blockers first);
   - read currency, timezone, campaigns and conversion actions from the account (read-only);
   - run the **contract gate** (`inspect_snapshot.py`) on the first real response;
   - ask you once, in a single grouped message, for what the account can't tell it.
3. When the blockers are cleared, say **"weekly review for last week"**.

### Adding other users
Colleagues, agencies, freelancers or client-side users each connect with their own Google login and
credentials, ideally with **Read-only** Google Ads access. See
[`docs/mcp-setup.md` › Adding other users](docs/mcp-setup.md#adding-other-users), which also covers removing access.

## Taking action — future
The system is designed to move from analysis to action **behind approval gates**. The pipeline exists;
writing is disabled. See [`docs/write-path.md`](docs/write-path.md).
- `scripts/gads/changes.py` models typed change requests (pause, budget, targets, negatives), with
  fingerprinted approval: editing a request after approval invalidates the approval.
- `config/execution.json` ships with `"writes_enabled": false`, and the only executor is `DisabledExecutor`.
- Google's MCP server is read-only, so a future executor would need the Google Ads API (an install you
  would approve first), dry-runs with `validate_only`, a change-log entry, and a verification snapshot.

## Security
- Never commit or paste credentials. `.mcp.json`, credential files, `data/` and `outputs/` are gitignored.
- **`.gitignore` is not access control.** It only stops files being committed. Ignored files are still
  readable by anyone or anything with access to your machine, including AI tools. Files committed before
  being ignored stay in git history. Keep credential files outside the repo and restrict their permissions.
- Account data can include search terms typed by real people; treat outputs as confidential.
- **The `.claude/settings.json` deny rules are best-effort.** They block Claude's Edit/Write tools on
  `data/raw/` and `config/execution.json` and the GoMarble connector, but not shell commands. The real
  Phase 1 safeguards are structural: snapshots are created with exclusive-create (never overwritten),
  the MCP client only calls read tools, and no write executor exists.

## Roadmap
1. **Connect** — run onboarding on your machine and pass the contract gate.
2. **Visual layer** — local HTML dashboard: trends, segment mix, issues, action status.
3. **Deeper analyses** — budget pacing, impression-share loss, PMax channels and assets, conversion audit, anomaly detection.
4. **Approved actions** — enable an executor for a short list of low-risk operations, one approved change at a time.
