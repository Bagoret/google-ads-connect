# Google Ads Connect — a local PPC operating system

A local, evidence-first system for analysing (and later managing) Google Ads for an e-commerce
business. It is reusable: every copy starts from clean templates, and every new person gets a
first-run setup. Claude Code runs the workflows; Python scripts do every
calculation; data comes from Google's official **read-only Google Ads MCP server** over OAuth.

**Status: Phase 1.** Read-only analysis engine, four skills, and the write-action groundwork are built
and tested on synthetic data. **No ad account is connected yet.**

## What it does
| Workflow | Skill | Script | Output |
|---|---|---|---|
| Fill business context, check readiness | `onboarding` | `scripts/context_status.py` | `outputs/onboarding/data-readiness.md` |
| Weekly performance review | `weekly-review` | `scripts/weekly_review.py` | report + action register |
| Search-term review | `search-term-review` | `scripts/search_terms.py` | review + negative candidates + conflicts + `dashboard.html` |
| Product review | `product-review` | `scripts/product_review.py` | item table + join check + `dashboard.html` |
| AI analysis + Ask box | `weekly-review` | `scripts/check_insights.py`, `scripts/ask_server.py` | verified AI insights on the dashboard; local Ask box (Claude Opus 5.5 via the official `anthropic` SDK, optional) |
| Visual dashboard | `weekly-review` | `scripts/dashboard.py` | `outputs/dashboard_*/index.html`: one offline HTML file (KPIs, daily trends, segment mix, issues, campaigns) |
| Check the OAuth/MCP connection | `onboarding` | `scripts/check_connection.py` | pass/fail checklist (no secrets printed) |
| Track proposed changes | – | `scripts/change_requests.py` | requests with approval history + `outputs/change-requests/status.html` |
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

### First run: every new person, any business
The project checks itself at the start of every Claude Code session (a `SessionStart` hook runs
`scripts/first_run.py --hook`). If something is missing, Claude runs the **onboarding** skill first:
- **Part 1, person setup (every new person, once per machine):** relationship to the business (owner,
  employee, agency, freelancer, consultant, client), Google Ads access level, intended use, and a connection check. Reports and pages are in English. Saved privately in `local/profile.json` (gitignored).
- **Part 2, business setup (once per business, or while blockers remain):** brand, market, search
  language, stocked brands, accounts in scope, revenue definition, plus optional targets and calendar.

**Using it for another business:** make a new copy of the repo (e.g. GitHub "Use this template", or a
fresh clone pushed to a new private repo), then run `python3 scripts/init_workspace.py --reset --yes` in
that copy. It replaces `context/` and the per-business config with the empty versions in `templates/`.
Never run `--reset` in the copy that holds your own business facts.

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

### Google Ads in Claude Desktop
Claude Desktop can use the same read-only server: see [`docs/claude-desktop.md`](docs/claude-desktop.md).

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
2. **Visual layer** — done: weekly dashboard (`scripts/dashboard.py`) and `dashboard.html` pages from the search-term and product reviews; change-request status page (`scripts/change_requests.py view`).
3. **Deeper analyses** — budget pacing, impression-share loss, PMax channels and assets, conversion audit, anomaly detection.
4. **Approved actions** — enable an executor for a short list of low-risk operations, one approved change at a time.
