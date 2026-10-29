import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.compare import Period  # noqa: E402
from gads.weekly.findings import ACTION_COLUMNS, Action, ReviewContext, generate_actions  # noqa: E402
from gads.core.metrics import Totals  # noqa: E402

DEFAULTS = {"min_clicks_for_ratio": 30, "material_pct_change": 20, "min_spend_zero_conv": None}
CUR = Period(date(2026, 10, 13), date(2026, 10, 19))
PREV = Period(date(2026, 10, 6), date(2026, 10, 12))


def T(cost="100", clicks=100, impressions=1000, conv="10", value="500"):
    return Totals(Decimal(cost), clicks, impressions,
                  None if conv is None else Decimal(conv), None if value is None else Decimal(value), 7)


def ctx(cur=None, prev=None, equivalent=True, thresholds=None, targets=None, caveats=None):
    cur = cur or T()
    account = {"current": cur}
    camp = {"current": cur}
    if prev is not None:
        account["previous"] = prev
        camp["previous"] = prev
    return ReviewContext(
        current=CUR, previous=PREV if prev is not None else None, equivalent=equivalent,
        account=account, campaigns={"9000000001": camp},
        campaign_meta={"9000000001": {"name": "SYNTH_Campaign_A", "campaign_type": "SEARCH", "brand_category": "unclassified"}},
        thresholds={**DEFAULTS, **(thresholds or {})}, targets=targets or {}, caveats=caveats or [],
        source_label="synthetic_snapshot.json", customer_id="9000000000",
    )


class ColumnsTest(unittest.TestCase):
    def test_columns_exact_order(self):
        self.assertEqual(ACTION_COLUMNS, ("priority", "entity_type", "entity_id", "finding", "supporting_metrics",
                                          "proposed_action", "rationale", "confidence", "risk",
                                          "approval_required", "validation_plan"))
        self.assertEqual(tuple(Action(*["x"] * 11).as_dict()), ACTION_COLUMNS)


class RulesTest(unittest.TestCase):
    def test_no_conversion_tracking_rule(self):
        acts = generate_actions(ctx(prev=T(clicks=100, conv="10"), cur=T(clicks=95, conv="0")))
        self.assertFalse([a for a in acts if "tracking" in a.proposed_action.lower()])

    def test_no_change_rules_when_not_equivalent(self):
        acts = generate_actions(ctx(equivalent=False, prev=T(cost="100"), cur=T(cost="300")))
        self.assertFalse([a for a in acts if "change" in a.finding.lower()])

    def test_material_change_reported_without_cause(self):
        acts = generate_actions(ctx(prev=T(cost="100"), cur=T(cost="300")))
        changes = [a for a in acts if "change" in a.finding.lower()]
        self.assertTrue(changes)
        for a in changes:
            self.assertTrue(a.proposed_action.startswith("Investigate"))
            self.assertNotIn("because", a.finding.lower())
            self.assertIn("2026-10-06", a.supporting_metrics)
            self.assertIn("synthetic_snapshot.json", a.supporting_metrics)

    def test_ratio_change_needs_min_clicks(self):
        acts = generate_actions(ctx(prev=T(clicks=10, conv="1", value="100"), cur=T(clicks=10, conv="1", value="10")))
        self.assertFalse([a for a in acts if "roas" in a.finding.lower()])

    def test_ratio_change_needs_min_conversions(self):
        # 1 -> 3 conversions on plenty of clicks: CPA/ROAS/CVR swing by hundreds of percent on noise
        few = dict(prev=T(clicks=300, conv="1", value="1"), cur=T(clicks=300, conv="3", value="14"))
        acts = generate_actions(ctx(**few, thresholds={"min_conversions_for_ratio": 10}))
        self.assertFalse([a for a in acts if any(m in a.finding for m in ("CPA", "ROAS", "CVR"))])
        enough = dict(prev=T(clicks=300, conv="10", value="100"), cur=T(clicks=300, conv="30", value="1400"))
        acts = generate_actions(ctx(**enough, thresholds={"min_conversions_for_ratio": 10}))
        self.assertTrue([a for a in acts if "ROAS" in a.finding])

    def test_min_conversions_null_disables_the_guard(self):
        acts = generate_actions(ctx(prev=T(clicks=300, conv="1", value="1"), cur=T(clicks=300, conv="3", value="14"),
                                    thresholds={"min_conversions_for_ratio": None}))
        self.assertTrue([a for a in acts if "ROAS" in a.finding])

    def test_cost_change_reported_even_with_few_conversions(self):
        acts = generate_actions(ctx(prev=T(cost="100", conv="1"), cur=T(cost="300", conv="1"),
                                    thresholds={"min_conversions_for_ratio": 10}))
        self.assertTrue([a for a in acts if "cost +200.0%" in a.finding])

    def test_r2_disabled_when_threshold_null(self):
        self.assertEqual(generate_actions(ctx(thresholds={"min_spend_zero_conv": None}, cur=T(cost="500", conv="0"))), [])

    def test_r2_fires_when_threshold_set(self):
        acts = generate_actions(ctx(thresholds={"min_spend_zero_conv": 200}, cur=T(cost="500", conv="0")))
        self.assertEqual([a.entity_id for a in acts], ["9000000001"])
        self.assertIn("0 conversions", acts[0].finding)

    def test_no_target_no_target_finding(self):
        self.assertFalse([a for a in generate_actions(ctx(targets={})) if "target" in a.finding.lower()])

    def test_target_roas_shortfall(self):
        acts = generate_actions(ctx(targets={"roas": Decimal("8")}, cur=T(cost="100", value="500")))
        self.assertTrue([a for a in acts if "target roas" in a.finding.lower()])

    def test_low_volume_is_low_confidence_p3(self):
        acts = generate_actions(ctx(thresholds={"min_spend_zero_conv": 1}, cur=T(cost="5", clicks=3, conv="0")))
        self.assertEqual((acts[0].confidence, acts[0].priority), ("low", "P3"))

    def test_caveats_cap_confidence(self):
        acts = generate_actions(ctx(thresholds={"min_spend_zero_conv": 1}, cur=T(cost="500", clicks=1000, conv="0"),
                                    caveats=["conversion delay unknown"]))
        self.assertEqual(acts[0].confidence, "medium")

    def test_every_action_requires_approval_and_has_entity_id(self):
        for a in generate_actions(ctx(prev=T(clicks=100, conv="10"), cur=T(clicks=95, conv="0"))):
            self.assertEqual(a.approval_required, "yes")
            self.assertTrue(a.entity_id)


if __name__ == "__main__":
    unittest.main()
