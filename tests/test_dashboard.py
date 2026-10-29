import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard import main  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SNAP = FIX / "synthetic_weekly_two_weeks.json"
BASE = ["--current", "2026-10-13:2026-10-19", "--expected-currency", "EUR", "--now", "2026-10-25T09:00:00+00:00"]


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, *extra, snapshot=SNAP):
        code = main(["--snapshot", str(snapshot), *BASE, *extra, "--out", str(self.out)])
        self.assertEqual(code, 0)
        page = next(self.out.glob("*/index.html"))
        return page.read_text(encoding="utf-8")

    def test_delay_note_only_while_conversions_can_still_arrive(self):
        self.assertIn("May still gain conversions", self.build())  # 6 days old, delay unknown
        for old in self.out.glob("*"):
            shutil.rmtree(old)
        code = main(["--snapshot", str(SNAP), "--current", "2026-10-13:2026-10-19", "--expected-currency", "EUR",
                     "--now", "2027-03-01T09:00:00+00:00", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertNotIn("May still gain conversions", next(self.out.glob("*/index.html")).read_text(encoding="utf-8"))

    def test_page_is_self_contained(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html))
        self.assertNotIn("<link", html)
        self.assertIn("prefers-color-scheme: dark", html)

    def test_kpis_come_from_the_engine(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        self.assertIn("SYNTHETIC", html)
        self.assertIn("273.00 EUR", html)   # current cost
        self.assertIn("630.00 EUR", html)   # previous conversion value
        self.assertIn("▼ -19.4%", html)     # ROAS delta 2.31 -> 1.86
        self.assertIn("1.86", html)         # ROAS

    def test_undefined_ratio_shows_na(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        row = re.search(r'<tr data-campaign="9000000003">.*?</tr>', html, re.S).group(0)
        self.assertIn("N/A", row)

    def test_stopped_campaign_flagged_with_label(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        row = re.search(r'<tr data-campaign="9000000004">.*?</tr>', html, re.S).group(0)
        self.assertIn("Stopped", row)
        self.assertIn("-100.0%", row)

    def test_actions_listed_with_priority_labels(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        self.assertIn("Priority 2", html)
        self.assertIn("9000000002", html)
        self.assertIn("approval", html.lower())

    def test_non_equivalent_periods_hide_deltas(self):
        html = self.build("--previous", "2026-10-07:2026-10-12")
        self.assertIn("not comparable", html)
        self.assertNotIn("▼ -19.4%", html)

    def test_daily_series_embedded_as_safe_json(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        m = re.search(r'<script type="application/json" id="dash-data">(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["daily"]), 14)
        self.assertEqual(data["daily"][0]["date"], "2026-10-06")
        self.assertEqual(data["daily"][7]["period"], "current")

    def test_untrusted_names_are_escaped(self):
        env = json.loads(SNAP.read_text())
        env["payload_text"] = env["payload_text"].replace("SYNTH_PMax_C", "<img src=x onerror=alert(1)></script>")
        evil = self.out / "evil.json"
        evil.write_text(json.dumps(env))
        html = self.build("--previous", "2026-10-06:2026-10-12", snapshot=evil)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("alert(1)></script>", html)
        self.assertIn("&lt;img src=x", html)

    def test_table_views_for_charts(self):
        html = self.build("--previous", "2026-10-06:2026-10-12")
        self.assertGreaterEqual(html.count("<details"), 2)

    def test_x_ticks_end_on_last_day_without_crowding(self):
        from gads.weekly.dashboard import _tick_indices
        for n in range(1, 120):
            ticks = _tick_indices(n)
            self.assertEqual((ticks[0], ticks[-1]), (0, n - 1))
            self.assertLessEqual(len(ticks), 8)
            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            if len(gaps) > 1:
                self.assertGreaterEqual(gaps[-1], 0.6 * gaps[0], n)

    def test_stop_writes_nothing(self):
        code = main(["--snapshot", str(SNAP), "--current", "2026-10-13:2026-10-19", "--expected-currency", "USD",
                     "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
