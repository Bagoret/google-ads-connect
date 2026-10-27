import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.connect.mcp_client import ALLOWED_TOOLS, McpStdioClient, ToolNotAllowed, extract_payload  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]


class RunLogTest(unittest.TestCase):
    def test_records_all_categories(self):
        log = RunLog()
        log.assume("a")
        log.warn("w")
        log.exclude(3, "bad clicks", {"metrics.clicks": "abc"})
        d = log.to_dict()
        self.assertEqual(d["assumptions"], ["a"])
        self.assertEqual(d["warnings"], ["w"])
        self.assertEqual(d["excluded"], [{"index": 3, "reason": "bad clicks", "raw": {"metrics.clicks": "abc"}}])
        self.assertEqual(d["errors"], [])

    def test_stop_analysis_carries_reason(self):
        self.assertEqual(StopAnalysis("why").reason, "why")


class ClientTest(unittest.TestCase):
    def test_call_allowed_tool_returns_result(self):
        env = {"FAKE_FIXTURE": str(FIX / "synthetic_search_ok.json")}
        with McpStdioClient(FAKE, env=env, timeout_s=20) as c:
            self.assertEqual(c.initialize()["name"], "fake-google-ads-mcp")
            tools = c.list_tools()
            self.assertIn("search_search", [t["name"] for t in tools])
            kind, payload = extract_payload(
                c.call_tool("search_search", {"customer_id": "9000000001", "fields": ["campaign.id"], "resource": "campaign"})
            )
        self.assertIn(kind, ("structured", "json_text"))
        self.assertIsInstance(payload, list)

    def test_disallowed_tool_never_sent(self):
        with McpStdioClient(FAKE, timeout_s=20) as c:
            c.initialize()
            with self.assertRaises(ToolNotAllowed):
                c.call_tool("mutate_campaign", {})

    def test_allowlist_is_read_only_names(self):
        for name in ALLOWED_TOOLS:
            for word in ("mutate", "create", "update", "remove", "delete", "propose"):
                self.assertNotIn(word, name)


class ExtractPayloadTest(unittest.TestCase):
    def test_is_error_stops(self):
        with self.assertRaises(StopAnalysis):
            extract_payload({"isError": True, "content": [{"type": "text", "text": "PERMISSION_DENIED"}]})

    def test_non_json_text_stops(self):
        with self.assertRaises(StopAnalysis):
            extract_payload({"content": [{"type": "text", "text": "Here are your campaigns:"}]})

    def test_structured_content_preferred(self):
        kind, payload = extract_payload({"structuredContent": {"results": []}, "content": [{"type": "text", "text": "x"}]})
        self.assertEqual((kind, payload), ("structured", {"results": []}))

    def test_json_text_floats_are_decimal(self):
        from decimal import Decimal
        kind, payload = extract_payload({"content": [{"type": "text", "text": "[{\"metrics.conversions\": 0.1}]"}]})
        self.assertEqual(kind, "json_text")
        self.assertEqual(payload[0]["metrics.conversions"], Decimal("0.1"))


if __name__ == "__main__":
    unittest.main()
