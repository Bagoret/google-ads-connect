import json
import sys
import unittest
from decimal import Decimal
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.core.normalize import apply_field_map, extract_rows, flatten_row, load_field_map, load_snapshot  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FMAP = load_field_map()


def records(name):
    snap = load_snapshot(FIX / name)
    log = RunLog()
    rows = [flatten_row(r) for r in extract_rows(snap.payload, log)]
    return apply_field_map(rows, FMAP, {"campaign_id", "date", "cost"}, log)


class SnapshotTest(unittest.TestCase):
    def test_load_snapshot_fields(self):
        snap = load_snapshot(FIX / "synthetic_campaign_daily_nested.json")
        self.assertTrue(snap.synthetic)
        self.assertEqual((snap.start, snap.end), (date(2026, 10, 1), date(2026, 10, 2)))
        self.assertEqual(snap.query_name, "campaign_daily")

    def test_error_snapshot_stops(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"query_name": "x", "gaql": "", "customer_id": "1", "start": None, "end": None,
                       "fetched_at": "", "payload_kind": "error", "payload": {"isError": True}}, fh)
        with self.assertRaises(StopAnalysis):
            load_snapshot(Path(fh.name))


class ShapeTest(unittest.TestCase):
    def test_three_shapes_normalise_identically(self):
        outs = [records(f"synthetic_campaign_daily_{s}.json") for s in ("nested", "dotted", "camel")]
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])
        self.assertEqual(outs[0][0]["campaign_id"], "9000000001")
        self.assertEqual(outs[0][0]["date"], date(2026, 10, 1))
        self.assertEqual(outs[0][0]["currency"], "EUR")

    def test_flatten_camel_case(self):
        self.assertEqual(flatten_row({"metrics": {"costMicros": "1"}}), {"metrics.cost_micros": "1"})

    def test_fastmcp_wrapped_result_accepted(self):
        rows = extract_rows({"result": [{"campaign.id": 9000000001}]}, RunLog())
        self.assertEqual(rows, [{"campaign.id": 9000000001}])

    def test_unknown_shape_stops(self):
        with self.assertRaises(StopAnalysis):
            extract_rows({"data": "something"}, RunLog())

    def test_pagination_token_stops(self):
        with self.assertRaises(StopAnalysis):
            extract_rows(load_snapshot(FIX / "synthetic_paginated.json").payload, RunLog())


class FieldMapTest(unittest.TestCase):
    def test_micros_to_currency(self):
        rec = apply_field_map([{"metrics.cost_micros": "12345678"}], FMAP, set(), RunLog())[0]
        self.assertEqual(rec["cost"], Decimal("12.345678"))

    def test_fractional_conversions_exact(self):
        rows = json.loads('[{"metrics.conversions": 0.1}, {"metrics.conversions": 0.2}]', parse_float=Decimal)
        recs = apply_field_map(rows, FMAP, set(), RunLog())
        self.assertEqual(sum(r["conversions"] for r in recs), Decimal("0.3"))

    def test_fixture_conversions_preserved(self):
        recs = records("synthetic_campaign_daily_dotted.json")
        self.assertEqual(recs[1]["conversions"], Decimal("0.33"))

    def test_missing_required_field_named(self):
        with self.assertRaisesRegex(StopAnalysis, "cost"):
            apply_field_map([{"campaign.id": "9000000001"}], FMAP, {"campaign_id", "cost"}, RunLog())

    def test_malformed_value_excluded_and_logged(self):
        log = RunLog()
        recs = apply_field_map([{"metrics.clicks": "abc"}, {"metrics.clicks": "3"}], FMAP, set(), log)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["clicks"], 3)
        self.assertEqual(log.to_dict()["excluded"][0]["index"], 0)

    def test_unmapped_fields_logged_not_dropped_silently(self):
        log = RunLog()
        apply_field_map([{"metrics.mystery": "1"}], FMAP, set(), log)
        self.assertTrue(any("metrics.mystery" in a for a in log.to_dict()["warnings"]))



class InspectCliTest(unittest.TestCase):
    def run_main(self, argv):
        import contextlib, io
        from inspect_snapshot import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_help_prints_usage(self):
        code, text = self.run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("Usage", text)

    def test_missing_file_stops_cleanly(self):
        code, text = self.run_main(["data/raw/does-not-exist.json"])
        self.assertEqual(code, 2)
        self.assertIn("STOP:", text)
        self.assertNotIn("Traceback", text)


class InspectTest(unittest.TestCase):
    def test_inspect_reports_shape_grain_and_ranges(self):
        from inspect_snapshot import inspect_snapshot
        info = inspect_snapshot(FIX / "synthetic_campaign_daily_camel.json")
        self.assertEqual(info["rows"], 2)
        self.assertEqual(info["date_range"], ["2026-10-01", "2026-10-02"])
        self.assertEqual(info["currencies"], ["EUR"])
        self.assertIn("campaign_id", info["canonical_fields"])
        self.assertEqual(info["grain"], ["campaign_id", "date"])
        self.assertTrue(info["synthetic"])


if __name__ == "__main__":
    unittest.main()
