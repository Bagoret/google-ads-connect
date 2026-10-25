import json
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.viz import fold_top  # noqa: E402
import product_review  # noqa: E402
import search_terms  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
LISTS = {"marketplace": ["SynthShop"], "stocked": ["SynthBrand"], "competitor": []}
EXTERNAL = re.compile(r"""(src|href)\s*=\s*["']?(https?:)?//""")


def self_contained(test, html):
    test.assertIsNone(EXTERNAL.search(html))
    test.assertNotIn("<link", html)
    test.assertIn("prefers-color-scheme: dark", html)


class FoldTopTest(unittest.TestCase):
    def test_folds_tail_into_other(self):
        rows = [(f"b{i}", Decimal(10 - i)) for i in range(10)]
        folded = fold_top(rows, 8)
        self.assertEqual(len(folded), 8)
        self.assertEqual(folded[-1], ("Other (3)", Decimal(6)))   # tail values 3 + 2 + 1
        self.assertEqual(folded[0], ("b0", Decimal(10)))

    def test_no_fold_when_short(self):
        rows = [("a", Decimal(1)), ("b", Decimal(2))]
        self.assertEqual(fold_top(rows, 8), [("b", Decimal(2)), ("a", Decimal(1))])


class SearchTermDashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.brands = self.out / "brands.json"
        self.brands.write_text(json.dumps(LISTS))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, terms=FIX / "synthetic_search_terms.json"):
        code = search_terms.main(["--search-terms", str(terms), "--keywords", str(FIX / "synthetic_keywords.json"),
                                  "--negatives", str(FIX / "synthetic_negatives.json"), "--brand-lists", str(self.brands),
                                  "--now", "2026-10-25T09:00:00+00:00", "--out", str(self.out / "o")])
        self.assertEqual(code, 0)
        return next((self.out / "o").glob("*/dashboard.html")).read_text(encoding="utf-8")

    def test_page_written_and_self_contained(self):
        html = self.run_cli()
        self_contained(self, html)
        self.assertIn("SYNTHETIC", html)
        self.assertIn("does not include every search query", html)

    def test_brand_split_and_flags(self):
        html = self.run_cli()
        self.assertIn("Cost by brand class", html)
        self.assertIn("<details", html)
        for label in ("stocked", "marketplace", "generic_or_unknown"):
            self.assertIn(label, html)
        self.assertIn("Weak performance", html)
        self.assertIn("Intent review pending", html)

    def test_conflicts_shown_with_label(self):
        html = self.run_cli()
        self.assertIn("Conflict", html)
        self.assertIn("synthbrand serum", html)

    def test_untrusted_term_escaped(self):
        env = json.loads((FIX / "synthetic_search_terms.json").read_text())
        env["payload_text"] = env["payload_text"].replace("free serum sample", "<script>alert(1)</script>")
        evil = self.out / "evil.json"
        evil.write_text(json.dumps(env))
        html = self.run_cli(evil)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)", html)


class ProductDashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra, products=FIX / "synthetic_product_daily.json"):
        code = product_review.main(["--products", str(products), "--now", "2026-10-25T09:00:00+00:00",
                                    "--out", str(self.out / "o"), *extra])
        self.assertEqual(code, 0)
        return next((self.out / "o").glob("*/dashboard.html")).read_text(encoding="utf-8")

    def test_page_written_and_self_contained(self):
        html = self.run_cli()
        self_contained(self, html)
        self.assertIn("SYNTHETIC", html)
        self.assertIn("Cost by brand", html)
        self.assertIn("<details", html)

    def test_no_margin_means_no_profit_language(self):
        html = self.run_cli()
        self.assertIn("not profitability", html)
        self.assertNotIn("Margin after ad cost", html)
        self.assertNotIn("profitable product", html.lower())

    def test_margin_and_stock_when_supplied(self):
        html = self.run_cli("--supplement", str(FIX / "synthetic_supplement_ok.json"))
        self.assertIn("Margin after ad cost", html)
        self.assertIn("16.00", html)          # synth-sku-001: 80 x 0.40 - 16
        self.assertIn("Low stock", html)      # synth-sku-002 stock_status low_stock
        self.assertIn("SYNTHETIC gross margin", html)

    def test_zero_conversion_spend_flagged(self):
        html = self.run_cli()
        row = re.search(r'<tr data-item="synth-sku-003">.*?</tr>', html, re.S).group(0)
        self.assertIn("No conversions", row)

    def test_join_check_visible(self):
        html = self.run_cli("--supplement", str(FIX / "synthetic_supplement_ok.json"))
        self.assertIn("synth-sku-999", html)  # in supplement, no performance

    def test_untrusted_title_escaped(self):
        env = json.loads((FIX / "synthetic_product_daily.json").read_text())
        env["payload_text"] = env["payload_text"].replace("SYNTH product SYNTH-SKU-003", "<img src=x onerror=alert(1)>")
        evil = self.out / "evil.json"
        evil.write_text(json.dumps(env))
        html = self.run_cli(products=evil)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x", html)


if __name__ == "__main__":
    unittest.main()
