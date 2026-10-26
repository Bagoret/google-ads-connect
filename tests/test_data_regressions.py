"""Regression tests for data-layer bugs found in the scope review."""
import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.normalize import apply_field_map, extract_rows, flatten_row, load_field_map, load_snapshot  # noqa: E402
import snapshot  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]


def fetch(tmp, fixture, **env):
    return snapshot.run_snapshot(query="campaign_daily", customer_id="9000000001", start=date(2026, 10, 1),
                                 end=date(2026, 10, 1), server_cmd=FAKE, raw_dir=Path(tmp),
                                 env={"FAKE_FIXTURE": str(FIX / fixture), **env})


class VerbatimTest(unittest.TestCase):
    def test_structured_numbers_survive_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fetch(tmp, "synthetic_search_high_precision.json")
            self.assertIn("0.12345678901234567890", path.read_text())  # the server's own digits, on disk
            rows = [flatten_row(r) for r in extract_rows(load_snapshot(path).payload, RunLog())]
            records = apply_field_map(rows, load_field_map(), {"campaign_id"}, RunLog())
            self.assertEqual(records[0]["conversions"], Decimal("0.12345678901234567890"))
            self.assertEqual(records[0]["conversion_value"], Decimal("2.0"))


class CustomerIdTest(unittest.TestCase):
    def test_one_rule_everywhere(self):
        from gads.ids import parse_customer_id
        for text in ("123-456-7890", " 123 456 7890 ", "customers/1234567890", "1234567890", "123.456.7890",
                     "(123) 456-7890"):
            self.assertEqual(parse_customer_id(text), "1234567890", text)
        for text in ("ID: 123-456-7890", "12345", "123-456-78901", "", None, "abc-def-ghij"):
            self.assertIsNone(parse_customer_id(text), text)


class WriteSafetyTest(unittest.TestCase):
    def test_unserialisable_envelope_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            with self.assertRaises(TypeError):
                snapshot.write_snapshot(path, {"bad": object()})
            self.assertFalse(path.exists())

    def test_write_never_overwrites_and_picks_a_free_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "snap.json"
            first.write_text("original")
            written = snapshot.write_snapshot(first, {"a": 1})  # e.g. a concurrent fetch took the name
            self.assertEqual(first.read_text(), "original")
            self.assertEqual(json.loads(written.read_text()), {"a": 1})

    def test_two_fetches_in_the_same_second_both_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = fetch(tmp, "synthetic_search_upstream_shape.json")
            b = fetch(tmp, "synthetic_search_upstream_shape.json")
            self.assertNotEqual(a, b)
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 2)


class CleanStopTest(unittest.TestCase):
    def test_missing_launcher_saves_error_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(StopAnalysis):
                snapshot.run_snapshot(query="customer_settings", customer_id="9000000001", start=None, end=None,
                                      server_cmd=["/nonexistent/launcher"], raw_dir=Path(tmp))
            saved = list(Path(tmp).glob("*.json"))
            self.assertEqual(json.loads(saved[0].read_text())["payload_kind"], "error")

    def test_malformed_mcp_json_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / ".mcp.json"
            for text in ("{not json", '{"mcpServers": {}}', '{"mcpServers": {"google-ads-mcp": {}}}'):
                cfg.write_text(text)
                with self.assertRaises(StopAnalysis, msg=text):
                    snapshot.load_server_config(cfg)

    def test_unsupported_gaql_clauses_stop(self):
        for q in ("SELECT campaign.id FROM campaign ORDER BY campaign.id",
                  "SELECT campaign.id FROM campaign WHERE campaign.status = 'ENABLED' LIMIT 5"):
            with self.assertRaises(StopAnalysis, msg=q):
                snapshot.parse_gaql(q)


class ClientDeadlineTest(unittest.TestCase):
    def test_notification_stream_cannot_extend_the_timeout(self):
        from gads.mcp_client import McpError, McpStdioClient
        client = McpStdioClient(["unused"], timeout_s=0.3)
        client._send = lambda message: None
        for _ in range(1000):
            client._lines.put('{"jsonrpc": "2.0", "method": "notifications/progress"}\n')
        with mock.patch("gads.mcp_client.time.monotonic", side_effect=[0.0] + [1.0] * 2000):
            with self.assertRaises(McpError):
                client._request("tools/call", {})
        client._stderr.close()


if __name__ == "__main__":
    unittest.main()
