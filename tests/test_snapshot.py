import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.logbook import StopAnalysis  # noqa: E402
from snapshot import build_search_args, parse_gaql, render_query, run_snapshot, write_snapshot  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]


UPSTREAM = json.loads((FIX / "upstream_golden_tools_list.json").read_text())["tools"]
SEARCH_SCHEMA = next(x for x in UPSTREAM if x["name"] == "search_search")["inputSchema"]


class ParseGaqlTest(unittest.TestCase):
    def test_between_kept_whole(self):
        q = render_query(ROOT / "queries" / "campaign_daily.gaql", date(2026, 10, 1), date(2026, 10, 14))
        parts = parse_gaql(q)
        self.assertEqual(parts["resource"], "campaign")
        self.assertEqual(parts["fields"][0], "customer.currency_code")
        self.assertEqual(parts["conditions"], ["segments.date BETWEEN '2026-10-01' AND '2026-10-14'"])

    def test_multiple_conditions(self):
        parts = parse_gaql(render_query(ROOT / "queries" / "keywords.gaql", None, None))
        self.assertEqual(parts["conditions"], ["ad_group_criterion.type = 'KEYWORD'", "ad_group_criterion.status != 'REMOVED'"])

    def test_no_where(self):
        self.assertEqual(parse_gaql("SELECT customer.id FROM customer")["conditions"], [])

    def test_every_library_query_parses(self):
        for q in (ROOT / "queries").glob("*.gaql"):
            parts = parse_gaql(render_query(q, date(2026, 10, 1), date(2026, 10, 2)))
            self.assertTrue(parts["fields"] and parts["resource"], q.name)


class BuildArgsTest(unittest.TestCase):
    def test_upstream_schema_gets_structured_args(self):
        args = build_search_args(SEARCH_SCHEMA, "9000000001", "SELECT campaign.id FROM campaign WHERE campaign.status = 'ENABLED'")
        self.assertEqual(args, {"customer_id": "9000000001", "fields": ["campaign.id"], "resource": "campaign",
                                "conditions": ["campaign.status = 'ENABLED'"]})

    def test_unknown_schema_stops(self):
        with self.assertRaises(StopAnalysis):
            build_search_args({"properties": {"customer_id": {}, "query": {}}}, "1", "SELECT a FROM b")


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
            self.assertEqual(env["tool_name"], "search_search")
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



class UpstreamContractTest(unittest.TestCase):
    def test_structured_arguments_sent_and_wrapped_result_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "args.json"
            path = run_snapshot(query="campaign_daily", customer_id="9000000001", start=date(2026, 10, 1),
                                end=date(2026, 10, 14), server_cmd=FAKE, raw_dir=Path(tmp) / "raw",
                                env={"FAKE_FIXTURE": str(FIX / "synthetic_search_upstream_shape.json"),
                                     "FAKE_RECORD": str(record)})
            sent = json.loads(record.read_text())
            self.assertEqual(sent["name"], "search_search")
            self.assertEqual(sent["arguments"]["resource"], "campaign")
            self.assertIn("metrics.cost_micros", sent["arguments"]["fields"])
            self.assertNotIn("query", sent["arguments"])
            from gads.logbook import RunLog
            from gads.normalize import extract_rows, load_snapshot
            rows = extract_rows(load_snapshot(path).payload, RunLog())
            self.assertEqual(rows[0]["campaign.id"], 9000000001)

    def test_protocol_failure_saved_without_stderr_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(StopAnalysis):
                run_snapshot(query="customer_settings", customer_id="9000000001", start=None, end=None,
                             server_cmd=FAKE, raw_dir=Path(tmp),
                             env={"FAKE_FIXTURE": str(FIX / "synthetic_search_ok.json"), "FAKE_MODE": "exit_on_call"})
            saved = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(saved), 1)
            text = saved[0].read_text()
            self.assertEqual(json.loads(text)["payload_kind"], "error")
            self.assertNotIn("SYNTH_STDERR_SECRET", text)


class ServerConfigTest(unittest.TestCase):
    def write_cfg(self, env):
        import tempfile
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"mcpServers": {"google-ads-mcp": {"command": "pipx", "args": ["run", "x"], "env": env}}}, fh)
        fh.close()
        return Path(fh.name)

    def test_env_var_references_expanded(self):
        import os
        from snapshot import load_server_config
        os.environ["SYNTH_TOKEN_FOR_TEST"] = "abc"
        cmd, env = load_server_config(self.write_cfg({"GOOGLE_ADS_DEVELOPER_TOKEN": "${SYNTH_TOKEN_FOR_TEST}"}))
        self.assertEqual(cmd, ["pipx", "run", "x"])
        self.assertEqual(env["GOOGLE_ADS_DEVELOPER_TOKEN"], "abc")

    def test_unset_env_var_stops(self):
        from snapshot import load_server_config
        with self.assertRaises(StopAnalysis):
            load_server_config(self.write_cfg({"X": "${SYNTH_DEFINITELY_UNSET_VAR}"}))

    def test_placeholder_stops(self):
        from snapshot import load_server_config
        with self.assertRaises(StopAnalysis):
            load_server_config(self.write_cfg({"GOOGLE_PROJECT_ID": "YOUR_PROJECT_ID"}))


if __name__ == "__main__":
    unittest.main()
