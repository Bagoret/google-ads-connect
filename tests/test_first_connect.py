"""First-connection runbook: every library query is fetched and contract-checked; the report is safe to share.

Runs against the fake MCP server with one synthetic response per query resource.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.connect.snapshot import parse_gaql, render_query  # noqa: E402
import first_connect  # noqa: E402

FAKE = f"{sys.executable} {ROOT / 'tests' / 'fake_mcp_server.py'}"
SECRET_LOOKING = "SYNTH_PRIVATE_CAMPAIGN_NAME"  # a value that must never reach the report


def value_for(field: str):
    if field == "segments.date":
        return "2026-10-01"
    if field.endswith("_micros"):
        return "1000000"
    if field.endswith((".id", "criterion_id")):
        return "9000000001"
    if field in ("metrics.clicks", "metrics.impressions", "conversion_action.click_through_lookback_window_days"):
        return "10"
    if field in ("metrics.conversions", "metrics.conversions_value"):
        return 1.5
    if field == "customer.currency_code":
        return "EUR"
    if field == "customer.time_zone":
        return "Europe/Paris"
    return SECRET_LOOKING


def write_fixtures(folder: Path, drop: dict[str, str] | None = None, empty: set[str] = frozenset(),
                   missing: set[str] = frozenset()) -> dict[str, str]:
    """One synthetic structured response per query resource; returns {resource: path}."""
    mapping = {}
    for q in sorted((ROOT / "queries").glob("*.gaql")):
        parts = parse_gaql(render_query(q, date(2026, 10, 1), date(2026, 10, 1)))
        if q.stem in missing:
            continue
        row = {f: value_for(f) for f in parts["fields"] if f != (drop or {}).get(q.stem)}
        rows = [] if q.stem in empty else [row]
        path = folder / f"{q.stem}.json"
        path.write_text(json.dumps({"_synthetic": "SYNTHETIC TEST DATA - NOT REAL",
                                    "result": {"structuredContent": {"result": rows},
                                               "content": [{"type": "text", "text": json.dumps(rows)}]}}))
        mapping.setdefault(parts["resource"], str(path))
    return mapping


class FirstConnectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "fx").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, mapping, *extra):
        import os
        old = os.environ.get("FAKE_FIXTURE_MAP")
        os.environ["FAKE_FIXTURE_MAP"] = json.dumps(mapping)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = first_connect.main(["--customer-id", "900-000-0001", "--server-cmd", FAKE,
                                           "--raw-dir", str(self.base / "raw"), "--out", str(self.base / "out"),
                                           "--end", "2026-10-14", *extra])
        finally:
            if old is None:
                os.environ.pop("FAKE_FIXTURE_MAP", None)
            else:
                os.environ["FAKE_FIXTURE_MAP"] = old
        folders = list((self.base / "out").glob("first-connect_*"))
        return code, out.getvalue() + err.getvalue(), folders

    def summary(self, folders):
        return json.loads((folders[0] / "summary.json").read_text())

    def test_all_queries_pass_and_every_feature_is_ready(self):
        code, text, folders = self.run_cli(write_fixtures(self.base / "fx"))
        self.assertEqual(code, 0, text)
        s = self.summary(folders)
        self.assertEqual(len(s["queries"]), len(list((ROOT / "queries").glob("*.gaql"))))
        self.assertTrue(all(q["status"] == "PASS" for q in s["queries"]), s["queries"])
        self.assertTrue(all(f["status"] == "READY" for f in s["features"]))
        self.assertEqual(s["period"], ["2026-10-01", "2026-10-14"])  # 14 days ending on --end
        self.assertEqual(len(list((self.base / "raw").glob("*.json"))), len(s["queries"]))  # verbatim snapshots kept

    def test_report_contains_no_account_values(self):
        _, _, folders = self.run_cli(write_fixtures(self.base / "fx"))
        for name in ("report.md", "summary.json"):
            self.assertNotIn(SECRET_LOOKING, (folders[0] / name).read_text(), name)

    def test_a_failing_query_blocks_its_feature_only_and_the_rest_still_run(self):
        mapping = write_fixtures(self.base / "fx")
        del mapping["search_term_view"]  # the fake server answers with a tool error
        code, text, folders = self.run_cli(mapping)
        self.assertEqual(code, 1)
        s = self.summary(folders)
        by_query = {q["query"]: q for q in s["queries"]}
        self.assertEqual(by_query["search_terms"]["status"], "FAIL")
        self.assertIn("no fixture", by_query["search_terms"]["detail"])
        self.assertEqual(by_query["campaign_daily"]["status"], "PASS")
        features = {f["feature"]: f["status"] for f in s["features"]}
        self.assertEqual(features["Search-term review"], "BLOCKED")
        self.assertEqual(features["Weekly review and dashboard"], "READY")
        self.assertIn("FAIL", (folders[0] / "report.md").read_text())

    def test_missing_required_field_fails_with_the_field_named(self):
        code, _, folders = self.run_cli(write_fixtures(self.base / "fx", drop={"campaign_daily": "metrics.cost_micros"}))
        self.assertEqual(code, 1)
        q = next(q for q in self.summary(folders)["queries"] if q["query"] == "campaign_daily")
        self.assertEqual(q["status"], "FAIL")
        self.assertIn("cost", q["detail"])

    def test_no_rows_is_reported_as_no_data_not_failure(self):
        code, _, folders = self.run_cli(write_fixtures(self.base / "fx", empty={"product_daily"}))
        self.assertEqual(code, 0)
        s = self.summary(folders)
        q = next(q for q in s["queries"] if q["query"] == "product_daily")
        self.assertEqual(q["status"], "EMPTY")
        self.assertEqual({f["feature"]: f["status"] for f in s["features"]}["Product review"], "NO DATA")

    def test_dates_outside_the_requested_period_fail(self):
        code, _, folders = self.run_cli(write_fixtures(self.base / "fx"), "--end", "2026-10-26")  # fixtures hold 10-01
        self.assertEqual(code, 1)
        q = next(q for q in self.summary(folders)["queries"] if q["query"] == "campaign_daily")
        self.assertEqual(q["status"], "FAIL")
        self.assertIn("outside the requested period", q["detail"])

    def test_bad_customer_id_stops_before_anything_runs(self):
        code, text, folders = self.run_cli({}, "--customer-id", "12345")
        self.assertEqual(code, 2)
        self.assertIn("STOP", text)
        self.assertEqual(folders, [])
        self.assertFalse((self.base / "raw").exists())


if __name__ == "__main__":
    unittest.main()
