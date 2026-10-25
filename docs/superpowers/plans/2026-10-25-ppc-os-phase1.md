# PPC OS Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, read-only Google Ads analysis system that pulls data through a Google Ads MCP server (OAuth), snapshots it verbatim, and turns it into validated, evidence-backed reports and an approval-gated action register.

**Architecture:** Three layers. *Knowledge*: `CLAUDE.md`, `context/`, `knowledge/`, `config/`. *Engine* (`scripts/gads/`, stdlib Python): a minimal stdio MCP client fetches GAQL results from a versioned query library into immutable JSON snapshots in `data/raw/`; pure functions then normalise → validate → aggregate → compare → apply findings rules → render. *Workflow*: `.claude/skills/*/SKILL.md` tell Claude which context to load, which script to run, when to stop, and what to output. Claude never transcribes numbers from MCP responses by hand — scripts fetch and compute.

**Tech Stack:** Python ≥ 3.10 standard library only (`json`, `decimal`, `datetime`, `zoneinfo`, `subprocess`, `argparse`, `unittest`). MCP server for live use (Phase 2, not installed now): `googleads/google-ads-mcp` run via `pipx`.

**Spec:** `docs/superpowers/specs/2026-10-25-ppc-os-design.md`

## Global Constraints
- No CSV ingestion or CSV outputs anywhere (user instruction 2026-10-25).
- No live account connection in Phase 1; all tests use synthetic fixtures and a fake MCP server; tests make no network calls.
- No external account writes. MCP client refuses any tool not in `ALLOWED_TOOLS`.
- No third-party Python packages. Any future install is proposed with an explanation first.
- Every fixture carries `"_synthetic": "SYNTHETIC TEST DATA - NOT REAL"`; entity names `SYNTH_*`, IDs `900000000N`.
- `data/raw/` files are created with exclusive-create (`open(path, "x")`) and never modified.
- Undefined ratios are `None` in code and `N/A` in output — never `0`.
- Money and conversions use `decimal.Decimal`; JSON is parsed with `parse_float=Decimal`.
- Action register columns, exact order: `priority, entity_type, entity_id, finding, supporting_metrics, proposed_action, rationale, confidence, risk, approval_required, validation_plan`.
- `approval_required` is always `"yes"` in Phase 1.

## Review Focus
1. MCP tool returns `isError`, or text that is not JSON → stop with the raw text saved; no partial report. (Task 2)
2. Response is paginated/truncated (`nextPageToken` non-empty) → stop; never analyse a partial result. (Task 4)
3. A campaign is renamed between periods → grouping by `campaign_id`, name shown from the latest row. (Task 9)
4. Current period ends today or later in the **account timezone** → partial-day caveat on all metrics. (Task 5)
5. Float conversions lose precision → `0.1 + 0.2` fractional conversions sum to exactly `0.3`. (Task 4)

## Decisions needing your confirmation
| # | Decision | Proposed default | Risk if wrong |
|---|---|---|---|
| D1 | MCP server | Google's official `googleads/google-ads-mcp` — tools: `search`, `list_accessible_customers`, `get_resource_metadata`; no write tools listed | Its `search` output format is **not documented**; Task 4 supports 3 shapes and stops on anything else. Verified on first live run (Task 10 gate). |
| D2 | GoMarble MCP (already connected to your claude.ai account; has `*_propose_*` write-type tools) | **Denied for this project** in `.claude/settings.json` | If you prefer GoMarble, we swap D1 and deny its propose tools individually. |
| D3 | How data reaches scripts | `scripts/snapshot.py` launches the MCP server over stdio and saves the verbatim response. Claude uses MCP interactively for exploration only | Claude copying large JSON by hand could alter numbers. |
| D4 | Where live runs happen | On **your machine** (Claude Code CLI/desktop) — OAuth credentials stay local. This cloud session only builds and tests | Cloud containers are ephemeral; putting OAuth secrets here is unnecessary risk. |
| D5 | Action register format | `actions.json` (machine-readable, feeds future dashboard) + `actions.md` (readable table). CSV removed per your instruction | Say if you still want a CSV *output* for spreadsheets. |
| D6 | Review sensitivity thresholds | `config/review_thresholds.json` ships defaults below, printed in every report as "defaults, not business-validated": `min_clicks_for_ratio: 30`, `material_pct_change: 20`, `min_spend_zero_conv: null` (rule off until you set it), `tracking_drop_pct: 50`, `tracking_click_stability_pct: 20` | These shape which findings surface; you should set them. |
| D7 | Campaign type / brand category | `config/campaign_classification.json` by campaign ID; fallback type = `campaign.advertising_channel_type`; fallback brand = `unclassified` | Guessing from names would invent structure. |
| D8 | Developer token | Not configured until setup; Google's page now marks it optional, an older source says required — verify at setup | Setup may fail without one. |
| D9 | Git workflow | Commit per task on branch `phase1-ppc-os`, PR to `main` at Checkpoint B | Say if you prefer committing to `main`. |

---

## File Structure
```
.claude/settings.json            permission deny rules (write-capable MCP tools, raw-data edits)
.mcp.json.example                official server config template (real .mcp.json is gitignored)
config/field_map.json            GAQL field path -> canonical name + type
config/review_thresholds.json    D6
config/campaign_classification.json  D7 (empty map initially)
config/brand_lists.json          marketplace / stocked / competitor names (empty = UNKNOWN)
queries/*.gaql                   versioned read-only GAQL: customer_settings, campaign_inventory,
                                 campaign_daily, conversion_actions, keywords, negative_keywords,
                                 search_terms, product_daily
scripts/gads/logbook.py          RunLog, StopAnalysis
scripts/gads/mcp_client.py       stdlib stdio JSON-RPC MCP client with tool allowlist
scripts/gads/normalize.py        snapshot loading, response-shape handling, field mapping
scripts/gads/validate.py         uniqueness, coverage, currency, partial-day checks
scripts/gads/metrics.py          Totals, aggregate, derive, fmt
scripts/gads/compare.py          Period, equivalence, pct_change
scripts/gads/findings.py         Action, ReviewContext, generate_actions
scripts/gads/report.py           render_report, write_outputs
scripts/snapshot.py              CLI: run a query via MCP -> data/raw/*.json
scripts/inspect_snapshot.py      CLI: shape, grain, fields, date range, currency of a snapshot
scripts/weekly_review.py         CLI: weekly review end to end
scripts/context_status.py        CLI: UNKNOWN fields -> blockers vs optional
scripts/search_terms.py          CLI: search-term review helper
scripts/product_review.py        CLI: product review helper
tests/fake_mcp_server.py         stdlib fake MCP server driven by fixture files
tests/fixtures/synthetic_*.json  labelled fixtures
tests/test_*.py                  one test module per engine module
.claude/skills/*/SKILL.md        four skills
docs/mcp-setup.md, README.md
```

---

### Task 1: Guardrails and query library

**Files:**
- Create: `.claude/settings.json`, `.mcp.json.example`, `config/field_map.json`, `config/review_thresholds.json`, `config/campaign_classification.json`, `config/brand_lists.json`, `queries/*.gaql` (8 files listed above)
- Test: `tests/test_guardrails.py`

**Interfaces:**
- Produces: GAQL files using only placeholders `{start}` and `{end}` (ISO dates); `field_map.json` shape `{"<gaql.path>": {"name": str, "type": "id"|"str"|"int"|"decimal"|"micros"|"date"}}`.

- [ ] **Step 1: Write the failing tests**
```python
def test_every_query_is_read_only_select():
    for q in Path("queries").glob("*.gaql"):
        text = q.read_text().upper()
        assert text.lstrip().startswith("SELECT"), q
        for word in ("MUTATE", "CREATE", "UPDATE", "REMOVE", "INSERT", "DELETE"):
            assert word not in text, (q, word)

def test_only_known_placeholders():
    for q in Path("queries").glob("*.gaql"):
        assert set(re.findall(r"\{(\w+)\}", q.read_text())) <= {"start", "end"}, q

def test_field_map_covers_every_selected_field():
    fmap = json.loads(Path("config/field_map.json").read_text())
    for q in Path("queries").glob("*.gaql"):
        for field in selected_fields(q.read_text()):
            assert field in fmap, (q.name, field)

def test_settings_deny_gomarble_and_raw_edits():
    deny = json.loads(Path(".claude/settings.json").read_text())["permissions"]["deny"]
    assert "mcp__GoMarble_AI" in deny
    assert "Edit(data/raw/**)" in deny and "Write(data/raw/**)" in deny
```
- [ ] **Step 2:** Run `python3 -m unittest tests.test_guardrails -v` → FAIL (files missing).
- [ ] **Step 3:** Create the files. `selected_fields(gaql: str) -> list[str]` lives in `tests/test_guardrails.py` (splits text between `SELECT` and `FROM` on commas). `campaign_daily.gaql` selects: `customer.currency_code, customer.time_zone, campaign.id, campaign.name, campaign.advertising_channel_type, campaign.status, segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value` `FROM campaign WHERE segments.date BETWEEN '{start}' AND '{end}'`. `.mcp.json.example` = the stdio/ADC config from Google's docs with placeholder values only.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: guardrails, config, and read-only GAQL library`.

### Task 2: Run log and MCP stdio client

**Files:**
- Create: `scripts/gads/__init__.py`, `scripts/gads/logbook.py`, `scripts/gads/mcp_client.py`, `tests/fake_mcp_server.py`, `tests/fixtures/synthetic_search_ok.json`, `tests/fixtures/synthetic_search_error.json`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces:
  - `class StopAnalysis(Exception)` with attribute `reason: str`.
  - `class RunLog` with `assume(msg: str)`, `warn(msg: str)`, `exclude(index: int, reason: str, raw: dict)`, `to_dict() -> dict` (keys `assumptions, warnings, excluded, errors`).
  - `ALLOWED_TOOLS: frozenset[str]` = `{"search", "list_accessible_customers", "get_resource_metadata", "search_search", "customers_list_accessible_customers", "metadata_get_resource_metadata"}`.
  - `class ToolNotAllowed(Exception)`.
  - `class McpStdioClient(command: list[str], env: dict[str, str] | None = None, timeout_s: float = 120)`; context manager; `initialize() -> dict` (returns `serverInfo`); `list_tools() -> list[dict]`; `call_tool(name: str, arguments: dict) -> dict`.
  - `extract_payload(result: dict) -> tuple[str, object]` → `("structured", obj)` from `structuredContent`, or `("json_text", obj)` from the first text item parsed with `parse_float=Decimal`; raises `StopAnalysis` on `isError` or non-JSON text.

- [ ] **Step 1: Write the failing tests**
```python
FAKE = [sys.executable, "tests/fake_mcp_server.py"]

def test_call_allowed_tool_returns_result():
    with McpStdioClient(FAKE, env={"FAKE_FIXTURE": "tests/fixtures/synthetic_search_ok.json"}) as c:
        assert c.initialize()["name"] == "fake-google-ads-mcp"
        kind, payload = extract_payload(c.call_tool("search", {"customer_id": "9000000001", "query": "SELECT ..."}))
        assert kind in ("structured", "json_text")

def test_disallowed_tool_never_sent():
    with McpStdioClient(FAKE) as c:
        c.initialize()
        with self.assertRaises(ToolNotAllowed):
            c.call_tool("mutate_campaign", {})

def test_is_error_stops():
    with self.assertRaises(StopAnalysis):
        extract_payload({"isError": True, "content": [{"type": "text", "text": "PERMISSION_DENIED"}]})

def test_non_json_text_stops():
    with self.assertRaises(StopAnalysis):
        extract_payload({"content": [{"type": "text", "text": "Here are your campaigns:"}]})
```
- [ ] **Step 2:** Run `python3 -m unittest tests.test_mcp_client -v` → FAIL.
- [ ] **Step 3:** Implement. Transport: newline-delimited JSON-RPC 2.0 over the child's stdin/stdout; `initialize` sends `protocolVersion`, `capabilities: {}`, `clientInfo`, then the `notifications/initialized` notification. `tests/fake_mcp_server.py` answers `initialize`, `tools/list` (returns `search` with an `inputSchema` having `customer_id` and `query`), and `tools/call` (returns the fixture file content).
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: stdlib MCP client with read-only tool allowlist`.

### Task 3: Snapshot CLI

**Files:**
- Create: `scripts/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `McpStdioClient`, `extract_payload`, `StopAnalysis` (Task 2); GAQL files (Task 1).
- Produces: `build_search_args(input_schema: dict, customer_id: str, query: str) -> dict` — picks the property whose name contains `customer` and the one containing `query`; raises `StopAnalysis` if either is missing or ambiguous. `render_query(path: Path, start: date, end: date) -> str`. Snapshot file `data/raw/<query>_<customer>_<start>_<end>_<UTC yyyymmddThhmmss>.json` with envelope keys: `query_name, gaql, customer_id, start, end, fetched_at, server_info, tool_name, payload_kind, payload`. CLI: `python3 scripts/snapshot.py --query campaign_daily --customer-id 1234567890 --start YYYY-MM-DD --end YYYY-MM-DD [--server-cmd "..."] [--raw-dir data/raw]`.

- [ ] **Step 1: Write the failing tests**
```python
def test_args_from_schema():
    schema = {"properties": {"customer_id": {}, "query": {}}}
    assert build_search_args(schema, "9000000001", "SELECT") == {"customer_id": "9000000001", "query": "SELECT"}

def test_ambiguous_schema_stops():
    with self.assertRaises(StopAnalysis):
        build_search_args({"properties": {"query": {}, "query_v2": {}, "customer_id": {}}}, "1", "q")

def test_snapshot_written_once_and_never_overwritten(tmp):
    path = run_snapshot(query="campaign_daily", customer_id="9000000001", start=date(2026,10,1), end=date(2026,10,14),
                        server_cmd=FAKE, raw_dir=tmp)
    env = json.loads(path.read_text())
    assert env["gaql"].count("2026-10-01") == 1 and env["customer_id"] == "9000000001"
    with self.assertRaises(FileExistsError):
        write_snapshot(path, env)
```
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `run_snapshot(...) -> Path` and `write_snapshot(path: Path, envelope: dict) -> None` (exclusive create). Customer ID accepted with or without dashes, stored without dashes.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: verbatim MCP snapshot CLI`.

### Task 4: Normalisation

**Files:**
- Create: `scripts/gads/normalize.py`, `scripts/inspect_snapshot.py`, fixtures `synthetic_campaign_daily_nested.json`, `synthetic_campaign_daily_dotted.json`, `synthetic_campaign_daily_camel.json`, `synthetic_paginated.json`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `RunLog`, `StopAnalysis`.
- Produces:
  - `@dataclass Snapshot(path: Path, query_name: str, gaql: str, customer_id: str, start: date, end: date, fetched_at: str, synthetic: bool, payload: object)`; `load_snapshot(path: Path) -> Snapshot`.
  - `extract_rows(payload: object, log: RunLog) -> list[dict]` — accepts a list, or a dict with `results` or `rows`; stops if `nextPageToken` is non-empty or shape unknown.
  - `flatten_row(row: dict) -> dict[str, object]` — nested → dotted, camelCase segments → snake_case (`metrics.costMicros` → `metrics.cost_micros`).
  - `apply_field_map(rows: list[dict], field_map: dict, required: set[str], log: RunLog) -> list[dict]` — canonical names; `micros` → `Decimal / 1_000_000`; `int` accepts int or numeric string; non-numeric value → row excluded via `log.exclude`; missing required canonical field → `StopAnalysis` naming it.
  - CLI `inspect_snapshot.py <file>` prints shape, row count, fields found/unmapped, date range, currencies, excluded rows.

- [ ] **Step 1: Write the failing tests**
```python
def test_three_shapes_normalise_identically():
    outs = [records(f"synthetic_campaign_daily_{s}.json") for s in ("nested", "dotted", "camel")]
    assert outs[0] == outs[1] == outs[2]

def test_micros_to_currency():
    assert apply_field_map([{"metrics.cost_micros": "12345678"}], FMAP, set(), RunLog())[0]["cost"] == Decimal("12.345678")

def test_fractional_conversions_exact():
    rows = json.loads('[{"metrics.conversions": 0.1}, {"metrics.conversions": 0.2}]', parse_float=Decimal)
    recs = apply_field_map(rows, FMAP, set(), RunLog())
    assert sum(r["conversions"] for r in recs) == Decimal("0.3")

def test_pagination_token_stops():
    with self.assertRaises(StopAnalysis):
        extract_rows(load_snapshot(FIX / "synthetic_paginated.json").payload, RunLog())

def test_missing_required_field_named():
    with self.assertRaisesRegex(StopAnalysis, "cost"):
        apply_field_map([{"campaign.id": "9000000001"}], FMAP, {"campaign_id", "cost"}, RunLog())

def test_malformed_value_excluded_and_logged():
    log = RunLog()
    recs = apply_field_map([{"metrics.clicks": "abc"}, {"metrics.clicks": "3"}], FMAP, set(), log)
    assert len(recs) == 1 and log.to_dict()["excluded"][0]["index"] == 0
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: snapshot normalisation with shape detection and exact decimals`.

### Task 5: Validation

**Files:** Create `scripts/gads/validate.py`; Test `tests/test_validate.py`

**Interfaces:**
- Produces:
  - `check_unique(records: list[dict], key: tuple[str, ...]) -> None` — `StopAnalysis` listing up to 20 duplicate keys.
  - `check_single_currency(records: list[dict], expected: str | None) -> str`.
  - `check_date_coverage(records: list[dict], start: date, end: date, log: RunLog) -> list[date]` — dates with zero rows → warning.
  - `partial_data_caveats(end: date, account_tz: str, lag_days: int | None, now_utc: datetime) -> list[str]`.

- [ ] **Step 1: Write the failing tests**
```python
def test_duplicate_grain_key_stops():
    recs = [{"campaign_id": "9000000001", "date": date(2026,10,1)}] * 2
    with self.assertRaisesRegex(StopAnalysis, "9000000001"):
        check_unique(recs, ("campaign_id", "date"))

def test_mixed_currency_stops():
    with self.assertRaises(StopAnalysis):
        check_single_currency([{"currency": "EUR"}, {"currency": "USD"}], None)

def test_expected_currency_mismatch_stops():
    with self.assertRaises(StopAnalysis):
        check_single_currency([{"currency": "USD"}], "EUR")

def test_partial_day_in_account_timezone():
    # 23:30 UTC on Oct 19 is already Oct 20 in Paris -> Oct 20 end date is partial
    c = partial_data_caveats(date(2026,10,20), "Europe/Paris", None, datetime(2026,10,19,23,30, tzinfo=UTC))
    assert any("partial" in x for x in c)

def test_unknown_lag_always_caveated():
    c = partial_data_caveats(date(2026,10,1), "Europe/Paris", None, datetime(2026,10,25, tzinfo=UTC))
    assert any("conversion delay unknown" in x for x in c)
```
- [ ] Steps 2–4: FAIL → implement → PASS. **Step 5:** Commit `feat: validation checks`.

### Task 6: Metrics

**Files:** Create `scripts/gads/metrics.py`; Test `tests/test_metrics.py`

**Interfaces:**
- Produces: `@dataclass Totals(cost: Decimal, clicks: int, impressions: int, conversions: Decimal | None, conversion_value: Decimal | None, rows: int)`; `aggregate(records: Iterable[dict]) -> Totals`; `group_by(records: Iterable[dict], key: str) -> dict[str, Totals]`; `derive(t: Totals) -> dict[str, Decimal | None]` with keys `cpc, ctr, cvr, cpa, roas, value_per_conversion`; `fmt(value: Decimal | int | None, kind: Literal["money","ratio","pct","count","conv"], currency: str = "") -> str`.

- [ ] **Step 1: Write the failing tests**
```python
def test_zero_conversions_cpa_is_none_not_zero():
    d = derive(Totals(Decimal("50"), 10, 100, Decimal("0"), Decimal("0"), 1))
    assert d["cpa"] is None and d["cvr"] == Decimal("0") and fmt(d["cpa"], "money") == "N/A"

def test_zero_clicks_and_zero_cost():
    d = derive(Totals(Decimal("0"), 0, 0, Decimal("0"), Decimal("0"), 1))
    assert d["cpc"] is None and d["cvr"] is None and d["roas"] is None

def test_missing_conversion_field_propagates_none():
    assert derive(Totals(Decimal("5"), 2, 9, None, None, 1))["cpa"] is None

def test_fractional_conversions_preserved_in_fmt():
    assert fmt(Decimal("2.67"), "conv") == "2.67"
```
- [ ] Steps 2–4. **Step 5:** Commit `feat: metrics with explicit N/A`.

### Task 7: Period comparison

**Files:** Create `scripts/gads/compare.py`; Test `tests/test_compare.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Period(start: date, end: date)` with `.days -> int`, `.weekday_counts() -> tuple[int, ...]`, `.contains(d: date) -> bool`, `Period.parse("YYYY-MM-DD:YYYY-MM-DD")`; `equivalence(cur: Period, prev: Period) -> tuple[bool, list[str]]`; `pct_change(cur: Decimal | None, prev: Decimal | None) -> Decimal | None`.

- [ ] **Step 1: Write the failing tests**
```python
def test_seven_vs_six_days_not_equivalent():
    ok, why = equivalence(Period(date(2026,10,13), date(2026,10,19)), Period(date(2026,10,7), date(2026,10,12)))
    assert not ok and any("length" in w for w in why)

def test_overlapping_periods_not_equivalent():
    ok, _ = equivalence(Period(date(2026,10,10), date(2026,10,16)), Period(date(2026,10,4), date(2026,10,10)))
    assert not ok

def test_consecutive_weeks_equivalent():
    assert equivalence(Period(date(2026,10,13), date(2026,10,19)), Period(date(2026,10,6), date(2026,10,12)))[0]

def test_pct_change_from_zero_or_none():
    assert pct_change(Decimal("5"), Decimal("0")) is None and pct_change(None, Decimal("1")) is None
```
- [ ] Steps 2–4. **Step 5:** Commit `feat: period equivalence`.

### Task 8: Findings rules and action register model

**Files:** Create `scripts/gads/findings.py`; Test `tests/test_findings.py`

**Interfaces:**
- Consumes: `Totals`, `derive` (Task 6); `Period`, `pct_change` (Task 7).
- Produces:
  - `ACTION_COLUMNS: tuple[str, ...]` = the 11 columns in Global Constraints order.
  - `@dataclass Action` with exactly those 11 `str` fields; `as_dict() -> dict`.
  - `@dataclass ReviewContext(current: Period, previous: Period | None, equivalent: bool, account: dict[str, Totals], campaigns: dict[str, dict[str, Totals]], campaign_meta: dict[str, dict], thresholds: dict, targets: dict, caveats: list[str], source_label: str)` — `account` / `campaigns[id]` keyed by `"current"` / `"previous"`.
  - `generate_actions(ctx: ReviewContext) -> list[Action]`, sorted P1 → P3, then by current cost desc.
- Rules (each `supporting_metrics` string includes period range(s) and `source_label`):
  - **R1 tracking** (P1, `entity_type="account"`): equivalent periods, previous conversions > 0, conversions fell ≥ `tracking_drop_pct`% while clicks changed ≤ `tracking_click_stability_pct`% → proposed action "Verify conversion tracking before any optimisation".
  - **R2 spend without conversions** (P2): only when `min_spend_zero_conv` is not null; campaign cost ≥ it and conversions == 0.
  - **R3 material change** (P2): equivalent periods only; |pct_change| ≥ `material_pct_change` on cost, cpa, roas, or cvr; both periods' clicks ≥ `min_clicks_for_ratio` for ratio metrics. Wording states the change, never a cause; proposed action starts "Investigate".
  - **R4 vs target** (P2): only if `targets` has `roas` or `cpa`.
  - Confidence: `high` if clicks ≥ 3× `min_clicks_for_ratio` and no caveats, `medium` if ≥ `min_clicks_for_ratio`, else `low`.

- [ ] **Step 1: Write the failing tests**
```python
def test_tracking_drop_is_p1():
    acts = generate_actions(ctx(prev=T(clicks=100, conv="10"), cur=T(clicks=95, conv="0")))
    assert acts[0].priority == "P1" and acts[0].entity_type == "account"

def test_no_change_rules_when_not_equivalent():
    acts = generate_actions(ctx(equivalent=False, prev=T(cost="100"), cur=T(cost="300")))
    assert not [a for a in acts if "change" in a.finding.lower()]

def test_r2_disabled_when_threshold_null():
    assert generate_actions(ctx(thresholds={"min_spend_zero_conv": None}, cur=T(cost="500", conv="0"))) == []

def test_no_target_no_target_finding():
    assert not [a for a in generate_actions(ctx(targets={})) if "target" in a.finding.lower()]

def test_every_action_requires_approval_and_has_entity_id():
    for a in generate_actions(ctx(prev=T(clicks=100, conv="10"), cur=T(clicks=95, conv="0"))):
        assert a.approval_required == "yes" and a.entity_id
```
(`ctx(...)` and `T(...)` are small builders defined in the test module.)
- [ ] Steps 2–4. **Step 5:** Commit `feat: rule-based findings and action model`.

### Task 9: Weekly review end to end + skill

**Files:**
- Create: `scripts/gads/report.py`, `scripts/weekly_review.py`, `.claude/skills/weekly-review/SKILL.md`, fixture `tests/fixtures/synthetic_weekly_two_weeks.json` (14 days, 3 SYNTH campaigns: one Search, one Shopping, one PMax; one renamed mid-range; one with zero conversions; fractional conversions; customer currency `EUR`, timezone `Europe/Paris`)
- Test: `tests/test_weekly_review_e2e.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `render_report(ctx: ReviewContext, actions: list[Action], log: RunLog, snapshot: Snapshot) -> str`; `write_outputs(out_root: Path, slug: str, report_md: str, actions: list[Action], log: RunLog) -> Path` (creates `outputs/<slug>/` — appends `-2`, `-3` if it exists; writes `report.md`, `actions.json`, `actions.md`, `run-log.json`). CLI: `python3 scripts/weekly_review.py --snapshot PATH --current A:B [--previous A:B] [--expected-currency EUR] [--conversion-lag-days N] [--target-roas X] [--target-cpa Y] [--now ISO8601] [--out outputs]`. Exit code 2 with the stop reason printed when `StopAnalysis` is raised; no output directory is created in that case.
- Report sections, in order: Sources & grain · Validation log · Comparison validity · Account totals · By campaign type · By brand category · By campaign · Observed material changes · Measurement caveats · Prioritised actions · Thresholds used · What this report cannot tell you. Every metric table shows clicks and conversions next to ratios.

- [ ] **Step 1: Write the failing tests**
```python
def test_end_to_end_outputs(tmp):
    out = run_cli("--snapshot", FIX/"synthetic_weekly_two_weeks.json", "--current", "2026-10-13:2026-10-19",
                  "--previous", "2026-10-06:2026-10-12", "--expected-currency", "EUR",
                  "--now", "2026-10-25T09:00:00+00:00", "--out", tmp)
    report = (out/"report.md").read_text()
    assert "SYNTHETIC" in report and "N/A" in report
    assert "conversion delay unknown" in report
    acts = json.loads((out/"actions.json").read_text())
    assert all(list(a) == list(ACTION_COLUMNS) for a in acts)

def test_renamed_campaign_grouped_by_id(tmp):
    report = ...  # same run
    assert report.count("9000000002") >= 1 and "SYNTH_Search_Renamed" in report and "SYNTH_Search_OldName" not in by_campaign_table(report)

def test_non_equivalent_periods_suppress_deltas(tmp):
    out = run_cli(..., "--previous", "2026-10-07:2026-10-12", ...)
    assert "Deltas suppressed" in (out/"report.md").read_text()

def test_stop_creates_no_output(tmp):
    code = run_cli_code(..., "--expected-currency", "USD", "--out", tmp)
    assert code == 2 and not any(Path(tmp).iterdir())
```
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `report.py`, `weekly_review.py`.
- [ ] **Step 4:** Write `SKILL.md` — frontmatter `name: weekly-review`, `description`; required inputs (customer ID, period(s), context loaded); context files (`business.md`, `account-map.md`, `measurement.md`, `commercial-calendar.md`, `knowledge/bidding-principles.md`); procedure = the spec's 12 steps mapped to `snapshot.py` → `inspect_snapshot.py` → `weekly_review.py`, passing `--conversion-lag-days` / targets **only** from context values that are not UNKNOWN, then cross-checking findings against the commercial calendar (labelled Hypothesis); stop conditions = any exit code 2, unknown response shape, UNKNOWN currency with no customer currency in data; output schema = the four files; explicit "never call write tools / never change the account".
- [ ] **Step 5:** Run full suite `python3 -m unittest discover -s tests -v` → PASS.
- [ ] **Step 6:** Commit `feat: weekly review end to end`.

**CHECKPOINT A — you review a sample report and action register generated from the synthetic fixture.**

### Task 10: Onboarding skill + MCP setup guide

**Files:** Create `scripts/context_status.py`, `.claude/skills/onboarding/SKILL.md`, `docs/mcp-setup.md`; Test `tests/test_context_status.py`

**Interfaces:**
- Produces: `@dataclass Field(file: str, section: str, name: str, value: str, blocking: bool)`; `scan_context(context_dir: Path) -> list[Field]` (rows whose value starts with `UNKNOWN`); `BLOCKING: set[tuple[str, str]]` = `(file, field-name prefix)` for: account currency, account timezone, customer ID(s), account(s) in scope, conversion actions table, conversion value definition, marketplace brand name, stocked product brands. CLI writes `outputs/onboarding/data-readiness.md`.

- [ ] **Step 1: Failing tests:** `test_unknown_fields_found` (temp context file with one UNKNOWN and one filled row → one Field); `test_currency_is_blocking`; `test_calendar_is_optional`.
- [ ] Steps 2–4: FAIL → implement → PASS.
- [ ] **Step 5:** `SKILL.md`: run `context_status.py`; ask only for missing items, blockers first, grouped (max one round of questions); **never ask for credentials, tokens, or secrets**; data-readiness checklist = MCP connected? `list_accessible_customers` returns the expected ID? → first `snapshot.py --query customer_settings` → `inspect_snapshot.py` confirms shape (**contract gate**: if shape unknown, stop and report) → which queries are runnable.
- [ ] **Step 6:** `docs/mcp-setup.md` for **your machine**: prerequisites (Google Cloud project, OAuth client or ADC with `https://www.googleapis.com/auth/adwords` scope, optional developer token), what `pipx` installs and why, copying `.mcp.json.example` → `.mcp.json`, verification steps. No commands are run by this plan.
- [ ] **Step 7:** Commit `feat: onboarding skill and MCP setup guide`.

### Task 11: Search-term review

**Files:** Create `scripts/search_terms.py`, `.claude/skills/search-term-review/SKILL.md`, fixtures `synthetic_search_terms.json`, `synthetic_negatives.json`, `synthetic_keywords.json`; Test `tests/test_search_terms.py`

**Interfaces:**
- Produces: `normalize_term(s: str) -> str` (casefold, strip accents, collapse spaces); `classify_brand(term: str, lists: dict[str, list[str]]) -> Literal["marketplace","stocked","competitor","generic_or_unknown"]`; `negative_blocks(neg_text: str, neg_match: Literal["EXACT","PHRASE","BROAD"], kw_text: str) -> bool` (approximation, documented); `find_conflicts(negatives: list[dict], keywords: list[dict]) -> list[dict]`; `weak_performance(records: list[dict], thresholds: dict) -> list[dict]`. CLI writes `outputs/search-terms-<range>/` with `review.md`, `candidates.json`. Stops if negatives or keywords snapshot missing.

- [ ] **Step 1: Failing tests:** `test_accents_normalised` (`"Crème"` → `"creme"`); `test_brand_lists_empty_gives_unknown`; `test_phrase_negative_blocks_keyword` (`"serum"` PHRASE blocks `"serum vitamine c"`); `test_exact_negative_does_not_block_longer_keyword`; `test_weak_performance_separate_from_intent` (output has no `irrelevant` label — intent is a Claude/human judgement step in the skill).
- [ ] Steps 2–4.
- [ ] **Step 5:** `SKILL.md`: required inputs; load `business.md` (brand lists), `approved-product-claims.md` (brand-owner rules), `search-principles.md`; procedure: snapshot 3 queries → script → Claude judges intent per term against catalog context, marking each as Observed/Hypothesis → negatives listed as **candidates** with match type and conflict status; report must state the search-terms data does not include every query; no writes.
- [ ] **Step 6:** Commit `feat: search-term review workflow`.

### Task 12: Product review

**Files:** Create `scripts/product_review.py`, `.claude/skills/product-review/SKILL.md`, fixtures `synthetic_product_daily.json`, `synthetic_supplement_ok.json`, `synthetic_supplement_dupes.json`; Test `tests/test_product_review.py`

**Interfaces:**
- Produces: `normalize_item_id(s: str) -> str` (strip + casefold; rule logged); `join_supplement(perf: dict[str, Totals], supplement: list[dict], log: RunLog) -> tuple[dict[str, dict], list[str], list[str]]` → (joined, ids only in performance, ids only in supplement); raises `StopAnalysis` on duplicate supplement keys. Supplement = optional JSON file `[{"item_id", "margin_rate"?, "stock_status"?}]` plus `"margin_definition"` at top level; without it, output has `revenue_roas` only. Grain documented as `item_id × period` aggregated from `item_id × campaign_id × date` (uniqueness checked on the latter).

- [ ] **Step 1: Failing tests:** `test_duplicate_supplement_keys_stop`; `test_unmatched_ids_listed_both_ways`; `test_no_margin_no_profit_label` (no key containing `profit` in output); `test_margin_without_definition_stops`; `test_duplicate_daily_rows_stop`.
- [ ] Steps 2–4.
- [ ] **Step 5:** `SKILL.md`: inputs, context (`business.md` profitability, `shopping-principles.md`, `commercial-calendar.md` stock), procedure, stop conditions, schema; "never label a product profitable from revenue ROAS"; no writes.
- [ ] **Step 6:** Commit `feat: product review workflow`.

### Task 13: README and final verification

**Files:** Create `README.md` (purpose, structure, quick start, how to run onboarding, security incl. "`.gitignore` is not access control", roadmap)

- [ ] **Step 1:** Write README.
- [ ] **Step 2:** Run `python3 -m unittest discover -s tests -v` → all PASS; paste summary into the PR body.
- [ ] **Step 3:** `git grep -niE "csv"` → only the "no CSV" constraint lines remain.
- [ ] **Step 4:** Commit, push `phase1-ppc-os`, open PR to `main`.

**CHECKPOINT B — final review: what is complete, what is untested (live MCP contract, real field names, OAuth flow), exact onboarding steps.**

---

## Roadmap (alignment only, not in this plan)
- **Phase 2 – Connect:** run `docs/mcp-setup.md` on your machine; contract gate on real `search` output; adjust `normalize.py` if needed.
- **Phase 3 – Visual:** local HTML dashboard from `data/processed/` (trends, segment mix, issues, action status).
- **Phase 4 – Deeper analyses:** budget pacing, impression-share loss, PMax channel/asset view, conversion-action audit, anomaly detection.
- **Phase 5 – Approved actions:** Google Ads Editor change files for manual upload first; API writes only later, behind per-change approval and change-log entries.
