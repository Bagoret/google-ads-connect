import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.findings import ACTION_COLUMNS  # noqa: E402
from weekly_review import main  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SNAP = str(FIX / "synthetic_weekly_two_weeks.json")
BASE = ["--snapshot", SNAP, "--current", "2026-10-13:2026-10-19", "--expected-currency", "EUR",
        "--now", "2026-10-25T09:00:00+00:00"]


def section(report: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", report, re.S | re.M)
    return m.group(1) if m else ""


class WeeklyReviewE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_ok(self, *extra):
        code = main(BASE + list(extra) + ["--out", str(self.out_root)])
        self.assertEqual(code, 0)
        dirs = list(self.out_root.iterdir())
        self.assertEqual(len(dirs), 1)
        return dirs[0]

    def test_end_to_end_outputs(self):
        out = self.run_ok("--previous", "2026-10-06:2026-10-12")
        report = (out / "report.md").read_text()
        self.assertIn("SYNTHETIC", report)
        self.assertIn("N/A", report)  # PMax CPA with zero conversions
        self.assertIn("conversion delay unknown", report)
        self.assertIn("synthetic_weekly_two_weeks.json", report)
        acts = json.loads((out / "actions.json").read_text())
        self.assertTrue(acts)
        for a in acts:
            self.assertEqual(tuple(a), ACTION_COLUMNS)
            self.assertEqual(a["approval_required"], "yes")
        self.assertTrue((out / "actions.md").exists())
        log = json.loads((out / "run-log.json").read_text())
        self.assertIn("log", log)
        self.assertIn("parameters", log)

    def test_sections_in_order(self):
        report = (self.run_ok("--previous", "2026-10-06:2026-10-12") / "report.md").read_text()
        titles = re.findall(r"^## (.+)$", report, re.M)
        self.assertEqual(titles, ["Sources & grain", "Validation log", "Comparison validity", "Account totals",
                                  "By campaign type", "By brand category", "By campaign",
                                  "Observed material changes", "Measurement caveats", "Prioritised actions",
                                  "Thresholds used", "What this report cannot tell you"])

    def test_fractional_conversions_in_report(self):
        report = (self.run_ok("--previous", "2026-10-06:2026-10-12") / "report.md").read_text()
        self.assertIn("2.31", section(report, "By campaign"))  # 7 x 0.33

    def test_renamed_campaign_grouped_by_id(self):
        report = (self.run_ok("--previous", "2026-10-06:2026-10-12") / "report.md").read_text()
        table = section(report, "By campaign")
        self.assertIn("9000000002", table)
        self.assertIn("SYNTH_Search_Renamed", table)
        self.assertNotIn("SYNTH_Search_OldName", table)
        self.assertEqual(table.count("9000000002"), 1)

    def test_segments_by_campaign_type(self):
        report = (self.run_ok() / "report.md").read_text()
        types = section(report, "By campaign type")
        for t in ("SHOPPING", "SEARCH", "PERFORMANCE_MAX"):
            self.assertIn(t, types)
        self.assertIn("unclassified", section(report, "By brand category"))

    def test_material_change_observed_for_search(self):
        out = self.run_ok("--previous", "2026-10-06:2026-10-12")
        acts = json.loads((out / "actions.json").read_text())
        self.assertTrue([a for a in acts if a["entity_id"] == "9000000002" and "cost +50.0%" in a["finding"]])

    def test_campaign_that_stopped_spending_is_reported(self):
        out = self.run_ok("--previous", "2026-10-06:2026-10-12")
        table = section((out / "report.md").read_text(), "By campaign")
        self.assertIn("9000000004", table)
        self.assertIn("-100.0%", table)
        acts = json.loads((out / "actions.json").read_text())
        stopped = [a for a in acts if a["entity_id"] == "9000000004" and "cost -100.0%" in a["finding"]]
        self.assertTrue(stopped)
        self.assertEqual(stopped[0]["priority"], "P2")  # judged on previous-period volume, not 0 clicks

    def test_non_equivalent_periods_suppress_deltas(self):
        out = self.run_ok("--previous", "2026-10-07:2026-10-12")
        report = (out / "report.md").read_text()
        self.assertIn("Deltas suppressed", report)
        acts = json.loads((out / "actions.json").read_text())
        self.assertFalse([a for a in acts if "change" in a["finding"].lower()])

    def test_stop_creates_no_output(self):
        code = main(BASE[:-4] + ["--expected-currency", "USD", "--now", "2026-10-25T09:00:00+00:00",
                                 "--out", str(self.out_root)])
        self.assertEqual(code, 2)
        self.assertFalse(any(self.out_root.iterdir()))

    def test_period_outside_snapshot_stops(self):
        code = main(["--snapshot", SNAP, "--current", "2026-10-20:2026-10-26", "--now", "2026-10-30T00:00:00+00:00",
                     "--out", str(self.out_root)])
        self.assertEqual(code, 2)
        self.assertFalse(any(self.out_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
