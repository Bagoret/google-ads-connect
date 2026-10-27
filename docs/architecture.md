# Architecture — components and boundaries

The engine in `scripts/gads/` is split into **components**. Each one is a package with one job, and imports only the
components below it. A mistake inside one component therefore cannot break a component that does not depend on it,
and each can be fixed and tested on its own. `tests/test_architecture.py` enforces this: it fails if a component
imports something it is not allowed to, and it imports each component with all the others it does not need blocked.

```
            scripts/*.py  (thin command-line entry points: parse flags, call components, write files)
                 │
   ┌─────────────┼───────────────────────────────┬──────────────┬─────────────┐
   ▼             ▼                               ▼              ▼             ▼
  ai ──────► present ──────► analysis ──────►  core  ◄────── connect     setup, changes
 (optional)  (pages, reports)  (computation)   (foundation)  (MCP server)  (onboarding, change requests)
```

| Component | Folder | Job | May import |
|---|---|---|---|
| **core** | `gads/core/` | Foundation: run log, IDs, paths, private files, CLI plumbing, metrics, period comparison, snapshot loading/normalising, validation | nothing else |
| **connect** | `gads/connect/` | Talking to Google's MCP server: stdio client with the read-only allowlist, `.mcp.json` loading, macOS shim | core |
| **analysis** | `gads/analysis/` | Computation only: weekly review, rule-based findings, search terms, products, threshold config | core |
| **present** | `gads/present/` | Rendering only: Markdown reports, HTML pages and charts | core, analysis, changes |
| **ai** | `gads/ai/` | Verified AI insights (`{{fact.key}}`), facts.json, the dashboard's AI and Ask sections | core, analysis, present |
| **changes** | `gads/changes/` | Approval-gated change requests (writes disabled) and loading saved requests | core |
| **setup** | `gads/setup/` | Business-context readiness for onboarding | core |

Scripts outside `gads/` (`snapshot.py`, `weekly_review.py`, `dashboard.py`, …) are entry points. No component imports a
script.

## Fault isolation (what keeps working when something breaks)
| If this breaks… | …this still works |
|---|---|
| A bad or invalid `insights.json` | Only the insights section is replaced by a notice; `facts.json`, the Ask box and the rest of the dashboard work |
| The `ai` component itself | The dashboard builds with "AI analysis is unavailable"; the weekly report is untouched |
| A page renderer in `present` (search-term or product dashboard) | `candidates.json` / `products.json` and `review.md` are still written; the page is skipped with a warning |
| `present` or `ai` | All of `analysis` (weekly, search terms, products) and its numbers |
| `analysis` | Fetching data (`connect`), onboarding (`setup`), change requests (`changes`) |
| The change-request status page (`present`) | `propose`, `approve`, `reject`, `list` (only `view` loads the page code) |
| `connect` | Every analysis on snapshots already saved in `data/raw/` |
| `core` | Nothing: it is the foundation, so it is kept small and fully tested |

## Fixing one component
1. Find the component in the table above; the fix stays inside its folder.
2. Run its tests, then the boundary and lint tests:
   ```bash
   python3 -m unittest tests.test_architecture tests.test_lint   # boundaries, isolation, undefined names
   python3 -m unittest discover -s tests                  # everything
   ```
   Tests per component: core → `test_normalize`, `test_metrics`, `test_compare`, `test_validate`;
   connect → `test_mcp_client`, `test_snapshot`, `test_check_connection`, `test_data_regressions`, `test_guardrails`; analysis → `test_findings`, `test_search_terms`,
   `test_product_review`, `test_weekly_review_e2e`, `test_review_regressions`; present → `test_dashboard`,
   `test_review_dashboards`; ai → `test_insights`, `test_ask_server`; changes → `test_changes`, `test_change_requests`;
   setup → `test_context_status`, `test_first_run`, `test_setup_*`.
3. If a fix seems to need a new import across components, check the table first: a lower layer must never import a
   higher one (e.g. `analysis` never imports `present`). Move the shared piece down into the lower component instead.

## Adding something new
- A new analysis: computation in `gads/analysis/<name>.py` (returns a result dataclass), rendering in
  `gads/present/<name>_page.py`, a thin `scripts/<name>.py` that writes the files. Optional outputs (pages) go through
  `core.cli.write_optional`, so a rendering bug never loses the data.
- A new component: add a package under `gads/` and a row to `ALLOWED` in `tests/test_architecture.py`.
