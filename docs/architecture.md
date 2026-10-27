# Architecture — features first, shared layers underneath

The engine in `scripts/gads/` is organised **by feature**: each job the system does (weekly review, search terms,
products, change requests, onboarding, AI) is one package. Underneath sit three small **shared** packages. Inside a
feature, the computation is kept apart from pages and reports. `tests/test_architecture.py` enforces all of it.

```
 scripts/*.py   thin entry points: read flags, call one feature, write files, set the exit code
      │
      ▼
 ┌─────────┐ ┌──────────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐      ┌──────┐
 │ weekly  │ │ search_terms │ │ products │ │ changes │ │ onboarding │      │  ai  │──► weekly
 └────┬────┘ └──────┬───────┘ └────┬─────┘ └────┬────┘ └─────┬──────┘      └──┬───┘
      └──── features never import each other (ai extends weekly) ─────────────┘
      ▼              ▼              ▼            ▼            ▼                ▼
 ┌──────────────────────────────── ui (page kit) ───────────────────────────────┐
 └──────────────────────────────── core (foundation) ───────────────────────────┘   connect (Google's server) → core
```

| Package | What it holds | Files | May import |
|---|---|---|---|
| **core** | Run log, IDs, files (+ repo root), CLI plumbing and exit codes, thresholds, metrics, period comparison, snapshot loading/normalising, validation | `gads/core/` | nothing else |
| **ui** | Page kit: charts, tiles, the self-contained page shell | `gads/ui/viz.py` | core |
| **connect** | Google's MCP server: read-only client, `.mcp.json` loading, macOS shim | `gads/connect/` | core |
| **weekly** | `analysis` (weekly review) · `findings` (rules) · `report` (Markdown) · `dashboard` (page) | `gads/weekly/` | core, ui |
| **search_terms** | `analysis` (brand classes, weak terms, conflicts) · `page` (Markdown + page) | `gads/search_terms/` | core, ui |
| **products** | `analysis` (item performance, margin join) · `page` (Markdown + page) | `gads/products/` | core, ui |
| **changes** | `pipeline` (approval-gated requests, writes disabled) · `store` (saved requests) · `page` (status page) | `gads/changes/` | core, ui |
| **onboarding** | `context` (which business facts are still UNKNOWN) | `gads/onboarding/` | core |
| **ai** | `insights` (verified `{{fact.key}}` text) · `dashboard_section` (facts.json, AI and Ask sections) | `gads/ai/` | core, ui, weekly |

**The three rules** (a test fails if one is broken):
1. Each package imports only what its row allows. Shared packages never import a feature.
2. Features are independent of each other. The one exception is `ai`, which extends the weekly review.
3. Inside a feature, the computation modules (`analysis`, `findings`, `pipeline`, `store`, `context`, `insights`)
   never import its pages, reports or the `ui` kit.

## Troubleshooting
**Where to look:** the problem's feature is the folder. "The product review numbers look wrong" → `gads/products/analysis.py`;
"the product page looks wrong" → `gads/products/page.py`; "can't fetch data" → `gads/connect/`.

**Exit codes** (all scripts):
| Code | Meaning |
|---|---|
| 0 | Done |
| 2 | `STOP:` — the data or inputs failed a check; the reason is printed and nothing is written |
| 3 | Done, but an **optional part** failed and was skipped (a dashboard page, the AI section). The main outputs are written; the full traceback with file and line is printed, followed by a summary line |
| 1 | Unexpected error (a bug in a main part); Python prints the traceback |

**Strict mode:** `GADS_STRICT=1 python3 scripts/<script>.py …` turns the optional-part safety net off, so the error
stops the run like any other (useful while fixing it). Disk errors are never caught by the safety net.

## What keeps working when something breaks
| If this breaks… | …this still works |
|---|---|
| A bad or invalid `insights.json` | Everything except the insights section (notice shown; exit 3); `facts.json` and the Ask box work |
| The `ai` package | The dashboard (with a notice; exit 3) and every report |
| A page in `search_terms` or `products` | `candidates.json` / `products.json` and `review.md` (exit 3) |
| Any one feature | Every other feature (rule 2) |
| `ui` | All computation in every feature (rule 3) |
| `connect` | Every review of snapshots already saved in `data/raw/` |

## Fixing or adding something
1. Change only the feature's folder. If you need something from another feature, move the shared piece down into
   `core` (or `ui` for display helpers) instead of importing across features.
2. Run its tests, then `python3 -m unittest tests.test_architecture tests.test_lint` (boundaries, isolation, undefined
   names), then the whole suite: `python3 -m unittest discover -s tests`.
   Tests per package: core → `test_normalize`, `test_metrics`, `test_compare`, `test_validate`;
   connect → `test_mcp_client`, `test_snapshot`, `test_check_connection`, `test_data_regressions`, `test_guardrails`;
   weekly → `test_findings`, `test_weekly_review_e2e`, `test_review_regressions`, `test_dashboard`;
   search_terms → `test_search_terms`, `test_review_dashboards`; products → `test_product_review`, `test_review_dashboards`;
   ai → `test_insights`, `test_ask_server`; changes → `test_changes`, `test_change_requests`;
   onboarding → `test_context_status`, `test_first_run`; Mac setup → `test_setup_config`, `test_setup_mac`.
3. A new feature: a package `gads/<feature>/` with `analysis.py` (returns a result dataclass) and `page.py`, a thin
   `scripts/<feature>.py`, a row in `ALLOWED` and `COMPUTE` in `tests/test_architecture.py`, and optional outputs written
   through `core.cli.write_optional` so a page bug never loses the data.
