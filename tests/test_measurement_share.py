"""Measurement check (conversions by action) and impression share in the weekly review and dashboard.
SYNTHETIC fixtures built on the synthetic two-week campaign snapshot (customer 9000000000, current 2026-10-13..19,
12.81 conversions)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dashboard  # noqa: E402
from weekly_review import main  # noqa: E402

SNAP = str(ROOT / "tests" / "fixtures" / "synthetic_weekly_two_weeks.json")
BASE = ["--snapshot", SNAP, "--current", "2026-10-13:2026-10-19", "--previous", "2026-10-06:2026-10-12",
        "--expected-currency", "EUR", "--now", "2026-10-25T09:00:00+00:00"]
PURCHASE = "customers/9000000000/conversionActions/7000000001"
PAGE_VIEW = "customers/9000000000/conversionActions/7000000002"


def envelope(query, rows, start="2026-10-13", end="2026-10-19", customer="9000000000"):
    return {"_synthetic": "SYNTHETIC TEST DATA - NOT REAL", "query_name": query, "gaql": "SELECT ...",
            "customer_id": customer, "start": start, "end": end, "fetched_at": "2026-10-25T09:00:00+00:00",
            "payload_kind": "json_text", "payload_text": json.dumps({"result": rows})}


def by_action(page_view_conv="3", purchase_conv="9.81"):
    return [
        {"segments.conversion_action": PURCHASE, "segments.conversion_action_name": "SYNTH Purchase",
         "segments.conversion_action_category": "PURCHASE", "metrics.conversions": purchase_conv,
         "metrics.conversions_value": "500", "metrics.all_conversions": purchase_conv,
         "metrics.all_conversions_value": "500"},
        {"segments.conversion_action": PAGE_VIEW, "segments.conversion_action_name": "SYNTH Page View",
         "segments.conversion_action_category": "PAGE_VIEW", "metrics.conversions": page_view_conv,
         "metrics.conversions_value": "3", "metrics.all_conversions": "1104", "metrics.all_conversions_value": "1104"},
    ]


SETTINGS = [
    {"conversion_action.id": "7000000001", "conversion_action.name": "SYNTH Purchase",
     "conversion_action.status": "ENABLED", "conversion_action.include_in_conversions_metric": True},
    {"conversion_action.id": "7000000002", "conversion_action.name": "SYNTH Page View",
     "conversion_action.status": "ENABLED", "conversion_action.include_in_conversions_metric": False},
]
SHARES = [
    {"campaign.id": "9000000001", "metrics.impressions": "1000", "metrics.search_impression_share": "0.4512",
     "metrics.search_budget_lost_impression_share": "0.1", "metrics.search_rank_lost_impression_share": "0.4488",
     "metrics.search_top_impression_share": "0.3", "metrics.search_absolute_top_impression_share": "0.1"},
    {"campaign.id": "9000000002", "metrics.impressions": "500", "metrics.search_impression_share": "0.0999",
     "metrics.search_budget_lost_impression_share": "0.9001", "metrics.search_rank_lost_impression_share": "0.02",
     "metrics.search_top_impression_share": "0.2", "metrics.search_absolute_top_impression_share": "0.05"},
]


class MeasurementShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, env):
        path = self.base / name
        path.write_text(json.dumps(env))
        return str(path)

    def inputs(self, conv=None, settings=True, shares=True):
        args = ["--conversions-snapshot", self.write("conv.json", conv or envelope("conversions_by_action", by_action()))]
        if settings:
            args += ["--conversion-settings-snapshot",
                     self.write("settings.json", envelope("conversion_actions", SETTINGS, None, None))]
        if shares:
            args += ["--share-snapshot", self.write("share.json", envelope("campaign_share", SHARES))]
        return args

    def review(self, *extra, expect=0):
        out = self.base / "out"
        code = main(BASE + list(extra) + ["--out", str(out)])
        self.assertEqual(code, expect)
        if expect:
            return None, None
        folder = next(out.iterdir())
        return (folder / "report.md").read_text(), json.loads((folder / "actions.json").read_text())

    def test_secondary_action_counted_in_conversions_is_a_p1_finding(self):
        report, actions = self.review(*self.inputs())
        first = actions[0]
        self.assertEqual((first["priority"], first["entity_type"], first["entity_id"]),
                         ("P1", "conversion_action", "7000000002"))
        self.assertIn("is set as secondary but counted 3.00 of 12.81 conversions", first["finding"])
        self.assertEqual(first["approval_required"], "yes")
        self.assertIn("Total by action matches", report)
        self.assertIn("| SYNTH Page View | 7000000002 | PAGE_VIEW | **secondary** | 3.00 |", report)

    def test_page_view_counted_without_settings_is_a_p2_finding(self):
        _, actions = self.review(*self.inputs(settings=False))
        pv = [a for a in actions if a["entity_id"] == "7000000002"]
        self.assertEqual(pv[0]["priority"], "P2")
        self.assertNotIn("secondary", pv[0]["finding"])

    def test_clean_measurement_raises_nothing(self):
        conv = envelope("conversions_by_action", by_action(page_view_conv="0", purchase_conv="12.81"))
        _, actions = self.review(*self.inputs(conv=conv))
        self.assertFalse([a for a in actions if a["entity_type"] == "conversion_action"])

    def test_totals_that_do_not_reconcile_are_flagged(self):
        conv = envelope("conversions_by_action", by_action(purchase_conv="5"))
        report, _ = self.review(*self.inputs(conv=conv))
        self.assertIn("**does not match**", report)
        self.assertIn("do not add up", report)

    def test_wrong_period_or_customer_stops(self):
        for env in (envelope("conversions_by_action", by_action(), start="2026-10-06"),
                    envelope("conversions_by_action", by_action(), customer="9000000099")):
            self.review(*self.inputs(conv=env), expect=2)

    def test_settings_without_conversions_snapshot_stops(self):
        self.review("--conversion-settings-snapshot",
                    self.write("settings.json", envelope("conversion_actions", SETTINGS, None, None)), expect=2)

    def test_impression_share_shows_capped_values_honestly(self):
        report, _ = self.review(*self.inputs())
        self.assertIn("| 9000000002 |", report)
        self.assertIn("< 10%", report)
        self.assertIn("> 90%", report)
        self.assertIn("45.12%", report)

    def test_without_new_inputs_the_report_says_the_check_did_not_run(self):
        report, _ = self.review()
        self.assertIn("Not run (no `--conversions-snapshot`)", report)
        self.assertNotIn("Impression share", report)

    def test_dashboard_shows_new_kpis_and_cards(self):
        out = self.base / "dash"
        code = dashboard.main(BASE + self.inputs() + ["--out", str(out)])
        self.assertEqual(code, 0)
        html = next(out.glob("*/index.html")).read_text(encoding="utf-8")
        self.assertIn('<td class="num">&lt; 10%</td>', html)
        banner = next(b for b in html.split('class="banner"')[1:] if "probably" in b).split("</div>", 1)[0]
        self.assertIn("probably not purchases", banner)
        self.assertIn("SYNTH Page View", banner)
        self.assertLess(html.index("probably not purchases"), html.index('class="kpis"'))
        for text in ("Measurement check", "SYNTH Page View", "secondary", "Impression share", "&lt; 10%",
                     "&gt; 90%", ">CTR<", ">Avg. CPC<", ">All conversions<"):
            self.assertIn(text, html)


if __name__ == "__main__":
    unittest.main()
