"""Last active day: one read-only query finds the latest day with impressions; first_connect uses it as the default
period end when the account has been quiet. Runs against the fake MCP server with synthetic rows."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.connect.activity import find_last_active  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402
import first_connect  # noqa: E402
import last_active  # noqa: E402

FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]
END = date(2026, 10, 27)


def rows(*days_impr):
    return [{"segments.date": d, "metrics.impressions": str(i), "metrics.cost_micros": "1000000"} for d, i in days_impr]


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, data):
        path = self.base / "fx.json"
        path.write_text(json.dumps({"_synthetic": "SYNTHETIC TEST DATA - NOT REAL",
                                    "result": {"structuredContent": {"result": data},
                                               "content": [{"type": "text", "text": json.dumps(data)}]}}))
        return mock.patch.dict(os.environ, {"FAKE_FIXTURE": str(path), "FAKE_RECORD": str(self.base / "call.json")})

    def test_latest_day_with_impressions_wins_and_zero_days_are_ignored(self):
        with self.fixture(rows(("2026-06-28", 5), ("2026-06-30", 12), ("2026-07-02", 0))):
            act = find_last_active("900-000-0001", FAKE, {}, self.base / "raw", END, 365)
        self.assertEqual(act.last_active, date(2026, 6, 30))
        self.assertEqual(act.active_days, 2)
        self.assertEqual(act.searched, (END - timedelta(days=364), END))
        self.assertEqual(act.suggested_period(7), (date(2026, 6, 24), date(2026, 6, 30)))
        call = json.loads((self.base / "call.json").read_text())["arguments"]
        self.assertEqual(call["resource"], "customer")
        self.assertIn("metrics.impressions > 0", call["conditions"])
        self.assertTrue(act.snapshot.exists())  # raw response kept verbatim

    def test_no_activity_returns_none(self):
        with self.fixture([]):
            act = find_last_active("900-000-0001", FAKE, {}, self.base / "raw", END, 30)
        self.assertIsNone(act.last_active)
        self.assertIsNone(act.suggested_period(7))

    def test_dates_outside_the_searched_period_stop(self):
        with self.fixture(rows(("2027-01-01", 3))), self.assertRaises(StopAnalysis):
            find_last_active("900-000-0001", FAKE, {}, self.base / "raw", END, 30)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = last_active.main(["--server-cmd", " ".join(FAKE), "--raw-dir", str(self.base / "raw"), *args])
        return code, out.getvalue(), err.getvalue()

    def test_cli_prints_the_day_and_a_ready_to_use_period(self):
        with self.fixture(rows(("2026-06-30", 12))):
            code, out, _ = self.run_cli("--customer-id", "900-000-0001", "--end", str(END))
        self.assertEqual(code, 0)
        self.assertIn("2026-06-30", out)
        self.assertIn("--start 2026-06-24 --end 2026-06-30", out)

    def test_cli_json_and_exit_1_when_nothing_found(self):
        with self.fixture([]):
            code, out, _ = self.run_cli("--customer-id", "900-000-0001", "--end", str(END), "--json")
        self.assertEqual(code, 1)
        self.assertIsNone(json.loads(out)["last_active"])

    def test_cli_bad_customer_id_stops(self):
        code, _, err = self.run_cli("--customer-id", "123")
        self.assertEqual(code, 2)
        self.assertIn("STOP", err)


class ChooseEndTest(unittest.TestCase):
    YESTERDAY = date(2026, 10, 27)

    def choose(self, last_active=None, error=None):
        from gads.connect.activity import Activity
        act = Activity((self.YESTERDAY - timedelta(days=364), self.YESTERDAY), last_active, 1 if last_active else 0,
                       Path("x.json"))
        with mock.patch.object(first_connect, "find_last_active", side_effect=error, return_value=act):
            return first_connect.choose_end("9000000001", [], {}, Path("."), self.YESTERDAY, 14)

    def test_paused_account_ends_on_last_active_day(self):
        end, note = self.choose(date(2026, 6, 30))
        self.assertEqual(end, date(2026, 6, 30))
        self.assertIn("last active", note)

    def test_recently_active_account_ends_yesterday(self):
        self.assertEqual(self.choose(date(2026, 10, 20))[0], self.YESTERDAY)

    def test_no_activity_or_failed_lookup_ends_yesterday(self):
        self.assertEqual(self.choose(None)[0], self.YESTERDAY)
        end, note = self.choose(error=StopAnalysis("synthetic failure"))
        self.assertEqual(end, self.YESTERDAY)
        self.assertIn("Could not look up", note)


if __name__ == "__main__":
    unittest.main()
