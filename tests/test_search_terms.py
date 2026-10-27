import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.analysis.search_terms import classify_brand, find_conflicts, negative_blocks, normalize_term, weak_performance  # noqa: E402
from search_terms import main  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
LISTS = {"marketplace": ["SynthShop"], "stocked": ["SynthBrand"], "competitor": ["RivalShop"]}


class NormalizeTest(unittest.TestCase):
    def test_accents_normalised(self):
        self.assertEqual(normalize_term("  Crème   SÉRUM "), "creme serum")


class BrandTest(unittest.TestCase):
    def test_brand_lists_empty_gives_unknown(self):
        self.assertEqual(classify_brand("synthbrand serum", {"marketplace": [], "stocked": [], "competitor": []}),
                         "generic_or_unknown")

    def test_classification_order(self):
        self.assertEqual(classify_brand("synthshop crème", LISTS), "marketplace")
        self.assertEqual(classify_brand("synthbrand sérum avis", LISTS), "stocked")
        self.assertEqual(classify_brand("rivalshop serum", LISTS), "competitor")
        self.assertEqual(classify_brand("serum vitamine c", LISTS), "generic_or_unknown")

    def test_token_boundary(self):
        self.assertEqual(classify_brand("synthbrandx serum", LISTS), "generic_or_unknown")


class NegativeBlocksTest(unittest.TestCase):
    def test_phrase_negative_blocks_keyword(self):
        self.assertTrue(negative_blocks("serum", "PHRASE", "serum vitamine c"))

    def test_phrase_requires_order(self):
        self.assertFalse(negative_blocks("vitamine serum", "PHRASE", "serum vitamine c"))

    def test_exact_negative_does_not_block_longer_keyword(self):
        self.assertFalse(negative_blocks("serum", "EXACT", "serum vitamine c"))
        self.assertTrue(negative_blocks("serum", "EXACT", "Serum"))

    def test_broad_any_order(self):
        self.assertTrue(negative_blocks("vitamine serum", "BROAD", "serum vitamine c"))


class ConflictTest(unittest.TestCase):
    def test_conflict_only_within_scope(self):
        negs = [{"keyword_text": "serum", "match_type": "PHRASE", "level": "campaign", "criterion_id": "6",
                 "scope_campaign_ids": ["1"]}]
        kws = [{"keyword_text": "synthbrand serum", "match_type": "PHRASE", "campaign_id": "1", "ad_group_id": "a",
                "criterion_id": "7"},
               {"keyword_text": "synthbrand serum", "match_type": "PHRASE", "campaign_id": "2", "ad_group_id": "b",
                "criterion_id": "8"}]
        conflicts = find_conflicts(negs, kws)
        self.assertEqual([c["keyword_criterion_id"] for c in conflicts], ["7"])


class WeakPerformanceTest(unittest.TestCase):
    def test_weak_performance_separate_from_intent(self):
        recs = [{"search_term": "a", "campaign_id": "1", "clicks": 40, "cost": Decimal("20"), "conversions": Decimal("0")},
                {"search_term": "b", "campaign_id": "1", "clicks": 3, "cost": Decimal("1"), "conversions": Decimal("0")}]
        flags = weak_performance(recs, {"min_clicks_for_ratio": 30, "min_spend_zero_conv": None})
        self.assertEqual([f["search_term"] for f in flags], ["a"])
        for f in flags:
            self.assertNotIn("irrelevant", json.dumps(f))

    def test_spend_threshold_flags_low_click_terms(self):
        recs = [{"search_term": "b", "campaign_id": "1", "clicks": 3, "cost": Decimal("12"), "conversions": Decimal("0")}]
        flags = weak_performance(recs, {"min_clicks_for_ratio": 30, "min_spend_zero_conv": 10})
        self.assertEqual([f["search_term"] for f in flags], ["b"])


class CliTest(unittest.TestCase):
    def test_stops_without_negatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--search-terms", str(FIX / "synthetic_search_terms.json"),
                         "--keywords", str(FIX / "synthetic_keywords.json"), "--out", tmp])
            self.assertEqual(code, 2)
            self.assertFalse(any(Path(tmp).iterdir()))

    def test_currency_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--search-terms", str(FIX / "synthetic_search_terms.json"),
                         "--keywords", str(FIX / "synthetic_keywords.json"),
                         "--negatives", str(FIX / "synthetic_negatives.json"),
                         "--expected-currency", "USD", "--out", tmp])
            self.assertEqual(code, 2)

    def test_caveats_and_currency_in_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--search-terms", str(FIX / "synthetic_search_terms.json"),
                         "--keywords", str(FIX / "synthetic_keywords.json"),
                         "--negatives", str(FIX / "synthetic_negatives.json"),
                         "--now", "2026-10-19T12:00:00+00:00", "--out", tmp])
            self.assertEqual(code, 0)
            review = (next(Path(tmp).iterdir()) / "review.md").read_text()
            self.assertIn("EUR", review)
            self.assertIn("partial", review)

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            brand = Path(tmp) / "brands.json"
            brand.write_text(json.dumps(LISTS))
            code = main(["--search-terms", str(FIX / "synthetic_search_terms.json"),
                         "--keywords", str(FIX / "synthetic_keywords.json"),
                         "--negatives", str(FIX / "synthetic_negatives.json"),
                         "--brand-lists", str(brand), "--out", tmp])
            self.assertEqual(code, 0)
            out = next(p for p in Path(tmp).iterdir() if p.is_dir())
            review = (out / "review.md").read_text()
            self.assertIn("does not include every search query", review)
            self.assertIn("SYNTHETIC", review)
            data = json.loads((out / "candidates.json").read_text())
            self.assertEqual(data["conflicts"][0]["negative_text"], "serum")  # blocks "synthbrand serum"
            self.assertTrue(all(t["intent_review"] == "PENDING" for t in data["terms"]))
            self.assertEqual({t["brand_class"] for t in data["terms"]},
                             {"stocked", "marketplace", "generic_or_unknown"})


if __name__ == "__main__":
    unittest.main()
