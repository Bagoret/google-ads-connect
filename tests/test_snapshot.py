import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.logbook import StopAnalysis  # noqa: E402
from snapshot import build_search_args, render_query, run_snapshot, write_snapshot  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]


class BuildArgsTest(unittest.TestCase):
    def test_args_from_schema(self):
        schema = {"properties": {"customer_id": {}, "query": {}}}
        self.assertEqual(build_search_args(schema, "9000000001", "SELECT"),
                         {"customer_id": "9000000001", "query": "SELECT"})

    def test_ambiguous_schema_stops(self):
        with self.assertRaises(StopAnalysis):
            build_search_args({"properties": {"query": {}, "query_v2": {}, "customer_id": {}}}, "1", "q")

    def test_missing_customer_param_stops(self):
        with self.assertRaises(StopAnalysis):
            build_search_args({"properties": {"query": {}}}, "1", "q")


class RenderQueryTest(unittest.TestCase):
    def test_dates_substituted(self):
        q = render_query(ROOT / "queries" / "campaign_daily.gaql", date(2026, 10, 1), date(2026, 10, 14))
        self.assertIn("BETWEEN '2026-10-01' AND '2026-10-14'", q)

    def test_dated_query_without_dates_stops(self):
        with self.assertRaises(StopAnalysis):
            render_query(ROOT / "queries" / "campaign_daily.gaql", None, None)

    def test_undated_query_ok(self):
        self.assertIn("FROM customer", render_query(ROOT / "queries" / "customer_settings.gaql", None, None))


class RunSnapshotTest(unittest.TestCase):
    def test_snapshot_written_once_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = run_snapshot(query="campaign_daily", customer_id="900-000-0001", start=date(2026, 10, 1),
                                end=date(2026, 10, 14), server_cmd=FAKE, raw_dir=Path(tmp),
                                env={"FAKE_FIXTURE": str(FIX / "synthetic_search_ok.json")})
            env = json.loads(path.read_text())
            self.assertEqual(env["gaql"].count("2026-10-01"), 1)
            self.assertEqual(env["customer_id"], "9000000001")
            self.assertEqual(env["tool_name"], "search")
            self.assertEqual(env["server_info"]["name"], "fake-google-ads-mcp")
            self.assertEqual(env["payload_kind"], "json_text")
            with self.assertRaises(FileExistsError):
                write_snapshot(path, env)

    def test_error_result_saved_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(StopAnalysis):
                run_snapshot(query="customer_settings", customer_id="9000000001", start=None, end=None,
                             server_cmd=FAKE, raw_dir=Path(tmp),
                             env={"FAKE_FIXTURE": str(FIX / "synthetic_search_error.json")})
            saved = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(json.loads(saved[0].read_text())["payload_kind"], "error")


if __name__ == "__main__":
    unittest.main()
