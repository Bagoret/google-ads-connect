import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.metrics import Totals  # noqa: E402
from product_review import join_supplement, main, normalize_item_id  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def perf():
    return {"synth-sku-001": Totals(Decimal("16"), 40, 400, Decimal("2"), Decimal("80"), 2),
            "synth-sku-003": Totals(Decimal("4"), 10, 400, Decimal("0"), Decimal("0"), 2)}


class JoinTest(unittest.TestCase):
    def test_normalize_item_id(self):
        self.assertEqual(normalize_item_id("  SYNTH-SKU-001 "), "synth-sku-001")

    def test_duplicate_supplement_keys_stop(self):
        items = json.loads((FIX / "synthetic_supplement_dupes.json").read_text())["items"]
        with self.assertRaisesRegex(StopAnalysis, "synth-sku-001"):
            join_supplement(perf(), items, RunLog())

    def test_unmatched_ids_listed_both_ways(self):
        items = [{"item_id": "SYNTH-SKU-001", "margin_rate": "0.4"}, {"item_id": "SYNTH-SKU-999", "margin_rate": "0.5"}]
        joined, only_perf, only_supp = join_supplement(perf(), items, RunLog())
        self.assertEqual(set(joined), {"synth-sku-001", "synth-sku-003"})
        self.assertEqual(only_perf, ["synth-sku-003"])
        self.assertEqual(only_supp, ["synth-sku-999"])

    def test_join_does_not_multiply_revenue(self):
        items = [{"item_id": "SYNTH-SKU-001", "margin_rate": "0.4"}]
        joined, _, _ = join_supplement(perf(), items, RunLog())
        self.assertEqual(joined["synth-sku-001"]["totals"].conversion_value, Decimal("80"))


class CliTest(unittest.TestCase):
    def run_cli(self, *extra):
        self.tmp = tempfile.TemporaryDirectory()
        code = main(["--products", str(FIX / "synthetic_product_daily.json"), "--out", self.tmp.name, *extra])
        dirs = [p for p in Path(self.tmp.name).iterdir()]
        return code, dirs

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_no_margin_no_profit_label(self):
        code, dirs = self.run_cli()
        self.assertEqual(code, 0)
        data = json.loads((dirs[0] / "products.json").read_text())
        text = json.dumps(data["products"]).lower()
        self.assertNotIn("profit", text)
        self.assertNotIn("margin", text)
        self.assertIn("revenue_roas", data["products"][0])
        review = (dirs[0] / "review.md").read_text()
        self.assertIn("not profitability", review.lower())
        self.assertIn("SYNTHETIC", review)

    def test_margin_supplement_adds_margin_columns(self):
        code, dirs = self.run_cli("--supplement", str(FIX / "synthetic_supplement_ok.json"))
        self.assertEqual(code, 0)
        data = json.loads((dirs[0] / "products.json").read_text())
        sku1 = next(p for p in data["products"] if p["item_id"] == "synth-sku-001")
        self.assertEqual(sku1["margin_after_ad_cost"], "16.00")  # 80*0.40 - 16
        self.assertEqual(sku1["stock_status"], "in_stock")
        self.assertEqual(data["unmatched"]["only_in_supplement"], ["synth-sku-999"])
        self.assertIn("SYNTHETIC gross margin", data["margin_definition"])

    def test_margin_without_definition_stops(self):
        code, dirs = self.run_cli("--supplement", str(FIX / "synthetic_supplement_no_definition.json"))
        self.assertEqual(code, 2)
        self.assertEqual(dirs, [])

    def test_duplicate_daily_rows_stop(self):
        self.tmp = tempfile.TemporaryDirectory()
        code = main(["--products", str(FIX / "synthetic_product_daily_dupes.json"), "--out", self.tmp.name])
        self.assertEqual(code, 2)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
