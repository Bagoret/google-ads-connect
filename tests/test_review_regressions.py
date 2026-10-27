"""Regression tests for bugs found in the scope review (analysis engine and change pipeline)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.analysis.findings import check_thresholds, generate_actions  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402
from gads.analysis.weekly import build_review  # noqa: E402
from weekly_review import build_parser, main as weekly_main  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
TWO_WEEKS = FIX / "synthetic_weekly_two_weeks.json"
ARGS = ["--current", "2026-10-13:2026-10-19", "--previous", "2026-10-06:2026-10-12",
        "--expected-currency", "EUR", "--now", "2026-10-25T09:00:00+00:00"]
THRESHOLDS = json.loads((ROOT / "config" / "review_thresholds.json").read_text())


def _quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        code = fn(*a)
    return code, err.getvalue()


class Snapshot:
    """Writes a modified copy of the two-week synthetic snapshot."""

    def __init__(self, tmp: Path, extra_rows=(), drop_keys=()):
        env = json.loads(TWO_WEEKS.read_text())
        rows = json.loads(env["payload_text"]) + list(extra_rows)
        env["payload_text"] = json.dumps(rows)
        for k in drop_keys:
            env.pop(k)
        self.path = tmp / "snap.json"
        self.path.write_text(json.dumps(env))


DISPLAY_PREVIOUS_ONLY = {
    "customer.currency_code": "EUR", "customer.time_zone": "Europe/Paris", "campaign.id": "9000000009",
    "campaign.name": "SYNTH_Display_Stopped", "campaign.advertising_channel_type": "DISPLAY",
    "campaign.status": "PAUSED", "segments.date": "2026-10-08", "metrics.impressions": "100",
    "metrics.clicks": "3", "metrics.cost_micros": "2000000", "metrics.conversions": 0.0,
    "metrics.conversions_value": 0.0,
}


class StoppedSegmentTest(unittest.TestCase):
    def test_segment_with_only_previous_rows_is_reported_not_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Snapshot(Path(tmp), [DISPLAY_PREVIOUS_ONLY])
            code, err = _quiet(weekly_main, ["--snapshot", str(snap.path), *ARGS, "--out", tmp + "/o"])
            self.assertEqual(code, 0, err)
            report = next(Path(tmp, "o").glob("*/report.md")).read_text()
            self.assertIn("DISPLAY", report)
            self.assertIn("9000000009", report)


class BadInputStopsCleanlyTest(unittest.TestCase):
    def test_invalid_or_non_positive_targets_stop(self):
        for flag, value in (("--target-roas", "abc"), ("--target-roas", "0"), ("--target-cpa", "-5")):
            with tempfile.TemporaryDirectory() as tmp:
                code, err = _quiet(weekly_main, ["--snapshot", str(TWO_WEEKS), *ARGS, flag, value, "--out", tmp])
                self.assertEqual(code, 2, (flag, value))
                self.assertIn("STOP", err)

    def test_snapshot_without_end_date_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Snapshot(Path(tmp), drop_keys=["end"])
            code, err = _quiet(weekly_main, ["--snapshot", str(snap.path), *ARGS, "--out", tmp + "/o"])
            self.assertEqual(code, 2)
            self.assertIn("outside the snapshot range", err)


class DatedSnapshotTest(unittest.TestCase):
    def test_dated_loader_requires_start_and_end(self):
        from gads.core.logbook import RunLog
        from gads.core.normalize import records_from_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            snap = Snapshot(Path(tmp), drop_keys=["end"])
            with self.assertRaises(StopAnalysis):
                records_from_snapshot(snap.path, {"campaign_id"}, RunLog(), dated=True)
            records_from_snapshot(snap.path, {"campaign_id"}, RunLog())  # undated use still allowed


class MissingInputFilesTest(unittest.TestCase):
    def test_missing_brand_lists_or_supplement_stop_cleanly(self):
        import product_review
        import search_terms
        with tempfile.TemporaryDirectory() as tmp:
            code, err = _quiet(search_terms.main, [
                "--search-terms", str(FIX / "synthetic_search_terms.json"), "--keywords", str(FIX / "synthetic_keywords.json"),
                "--negatives", str(FIX / "synthetic_negatives.json"), "--brand-lists", tmp + "/missing.json", "--out", tmp + "/o"])
            self.assertEqual(code, 2)
            self.assertIn("cannot read brand lists", err)
            Path(tmp, "bad.json").write_text("[1, 2]")
            code, err = _quiet(product_review.main, [
                "--products", str(FIX / "synthetic_product_daily.json"), "--supplement", tmp + "/bad.json",
                "--out", tmp + "/o"])
            self.assertEqual(code, 2)
            self.assertFalse(Path(tmp, "o").exists())


class ThresholdsTest(unittest.TestCase):
    def ctx(self, **over):
        review = build_review(build_parser().parse_args(["--snapshot", str(TWO_WEEKS), *ARGS]))
        review.ctx.thresholds = {**THRESHOLDS, **over}
        return review.ctx

    def test_null_disables_each_rule_without_crashing(self):
        for key in ("material_pct_change", "min_spend_zero_conv"):
            generate_actions(self.ctx(**{key: None}))  # must not raise

    def test_null_material_threshold_removes_material_findings(self):
        actions = generate_actions(self.ctx(material_pct_change=None))
        self.assertFalse([a for a in actions if a.finding.startswith("Material change")])

    def test_required_and_typed_values_checked(self):
        with self.assertRaises(StopAnalysis):
            check_thresholds({**THRESHOLDS, "min_clicks_for_ratio": None})
        with self.assertRaises(StopAnalysis):
            check_thresholds({**THRESHOLDS, "material_pct_change": "20"})
        with self.assertRaises(StopAnalysis):
            check_thresholds({**THRESHOLDS, "material_pct_change": -1})
        with self.assertRaises(StopAnalysis):
            check_thresholds({**THRESHOLDS, "material_pct_change": float("nan")})
        check_thresholds(THRESHOLDS)


class ChangeRequestParsingTest(unittest.TestCase):
    def test_keyword_text_stays_text(self):
        from change_requests import _parse_value
        self.assertEqual(_parse_value("text", "007"), "007")
        self.assertEqual(_parse_value("match_type", "1"), "1")
        self.assertEqual(_parse_value("campaign_id", "9000000001"), 9000000001)

    def test_rolled_back_revision_is_loaded(self):
        from change_requests import load_requests
        with tempfile.TemporaryDirectory() as tmp:
            base = {"id": "CR-20261026-0001", "customer_id": "9000000000", "operation": "pause_campaign",
                    "params": {"campaign_id": 1}, "rationale": "r", "evidence": "e"}
            Path(tmp, "CR-20261026-0001_04_executed.json").write_text(json.dumps({**base, "status": "executed"}))
            Path(tmp, "CR-20261026-0001_05_rolled_back.json").write_text(json.dumps({**base, "status": "rolled_back"}))
            self.assertEqual(load_requests(Path(tmp))["CR-20261026-0001"].status, "rolled_back")


class ActiveKeywordsTest(unittest.TestCase):
    def test_paused_and_negative_keywords_excluded_from_conflict_check(self):
        from gads.analysis.search_terms import active_keywords
        rows = [{"keyword_text": "a", "negative": "false", "criterion_status": "ENABLED"},
                {"keyword_text": "b", "negative": "false", "criterion_status": "PAUSED"},
                {"keyword_text": "c", "negative": "true", "criterion_status": "ENABLED"},
                {"keyword_text": "d", "negative": "false"}]
        self.assertEqual([k["keyword_text"] for k in active_keywords(rows)], ["a", "d"])


if __name__ == "__main__":
    unittest.main()
