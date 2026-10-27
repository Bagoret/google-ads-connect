import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.metrics import Totals, aggregate, derive, fmt, group_by  # noqa: E402

D = Decimal


class AggregateTest(unittest.TestCase):
    def test_sums_with_fractional_conversions(self):
        t = aggregate([
            {"cost": D("1.5"), "clicks": 2, "impressions": 10, "conversions": D("0.33"), "conversion_value": D("5")},
            {"cost": D("2.5"), "clicks": 3, "impressions": 20, "conversions": D("0.67"), "conversion_value": D("7")},
        ])
        self.assertEqual(t, Totals(D("4.0"), 5, 30, D("1.00"), D("12"), 2))

    def test_missing_conversions_field_gives_none(self):
        t = aggregate([{"cost": D("1"), "clicks": 1, "impressions": 1}])
        self.assertIsNone(t.conversions)
        self.assertIsNone(t.conversion_value)

    def test_group_by_campaign(self):
        g = group_by([{"campaign_id": "1", "cost": D("1"), "clicks": 1, "impressions": 1},
                      {"campaign_id": "1", "cost": D("2"), "clicks": 1, "impressions": 1},
                      {"campaign_id": "2", "cost": D("5"), "clicks": 0, "impressions": 3}], "campaign_id")
        self.assertEqual(g["1"].cost, D("3"))
        self.assertEqual(g["2"].rows, 1)


class DeriveTest(unittest.TestCase):
    def test_zero_conversions_cpa_is_none_not_zero(self):
        d = derive(Totals(D("50"), 10, 100, D("0"), D("0"), 1))
        self.assertIsNone(d["cpa"])
        self.assertEqual(d["cvr"], D("0"))
        self.assertEqual(fmt(d["cpa"], "money"), "N/A")

    def test_zero_clicks_and_zero_cost(self):
        d = derive(Totals(D("0"), 0, 0, D("0"), D("0"), 1))
        self.assertIsNone(d["cpc"])
        self.assertIsNone(d["cvr"])
        self.assertIsNone(d["roas"])
        self.assertIsNone(d["ctr"])

    def test_missing_conversion_field_propagates_none(self):
        d = derive(Totals(D("5"), 2, 9, None, None, 1))
        self.assertIsNone(d["cpa"])
        self.assertIsNone(d["roas"])
        self.assertIsNone(d["cvr"])

    def test_values(self):
        d = derive(Totals(D("40"), 20, 400, D("2"), D("100"), 1))
        self.assertEqual(d["cpc"], D("2"))
        self.assertEqual(d["ctr"], D("0.05"))
        self.assertEqual(d["cvr"], D("0.1"))
        self.assertEqual(d["cpa"], D("20"))
        self.assertEqual(d["roas"], D("2.5"))
        self.assertEqual(d["value_per_conversion"], D("50"))


class FmtTest(unittest.TestCase):
    def test_fractional_conversions_preserved_in_fmt(self):
        self.assertEqual(fmt(D("2.67"), "conv"), "2.67")

    def test_formats(self):
        self.assertEqual(fmt(D("12.345"), "money", "EUR"), "12.35 EUR")
        self.assertEqual(fmt(D("0.05"), "pct"), "5.00%")
        self.assertEqual(fmt(D("2.5"), "ratio"), "2.50")
        self.assertEqual(fmt(1234, "count"), "1,234")
        self.assertEqual(fmt(None, "pct"), "N/A")


if __name__ == "__main__":
    unittest.main()
