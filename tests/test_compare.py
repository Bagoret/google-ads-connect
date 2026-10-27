import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.compare import Period, equivalence, pct_change  # noqa: E402
from gads.core.logbook import StopAnalysis  # noqa: E402


class PeriodTest(unittest.TestCase):
    def test_parse_and_days(self):
        p = Period.parse("2026-10-13:2026-10-19")
        self.assertEqual((p.start, p.end, p.days), (date(2026, 10, 13), date(2026, 10, 19), 7))
        self.assertTrue(p.contains(date(2026, 10, 15)))
        self.assertFalse(p.contains(date(2026, 10, 20)))

    def test_parse_reversed_stops(self):
        with self.assertRaises(StopAnalysis):
            Period.parse("2026-10-19:2026-10-13")

    def test_weekday_counts(self):
        self.assertEqual(Period(date(2026, 10, 13), date(2026, 10, 19)).weekday_counts(), (1,) * 7)


class EquivalenceTest(unittest.TestCase):
    def test_seven_vs_six_days_not_equivalent(self):
        ok, why = equivalence(Period(date(2026, 10, 13), date(2026, 10, 19)), Period(date(2026, 10, 7), date(2026, 10, 12)))
        self.assertFalse(ok)
        self.assertTrue(any("length" in w for w in why))

    def test_overlapping_periods_not_equivalent(self):
        ok, why = equivalence(Period(date(2026, 10, 10), date(2026, 10, 16)), Period(date(2026, 10, 4), date(2026, 10, 10)))
        self.assertFalse(ok)
        self.assertTrue(any("overlap" in w for w in why))

    def test_same_length_different_weekday_mix(self):
        ok, why = equivalence(Period(date(2026, 10, 13), date(2026, 10, 15)), Period(date(2026, 10, 3), date(2026, 10, 5)))
        self.assertFalse(ok)
        self.assertTrue(any("weekday" in w for w in why))

    def test_consecutive_weeks_equivalent(self):
        self.assertEqual(equivalence(Period(date(2026, 10, 13), date(2026, 10, 19)),
                                     Period(date(2026, 10, 6), date(2026, 10, 12))), (True, []))


class PctChangeTest(unittest.TestCase):
    def test_pct_change_from_zero_or_none(self):
        self.assertIsNone(pct_change(Decimal("5"), Decimal("0")))
        self.assertIsNone(pct_change(None, Decimal("1")))
        self.assertIsNone(pct_change(Decimal("1"), None))

    def test_pct_change_value(self):
        self.assertEqual(pct_change(Decimal("150"), Decimal("100")), Decimal("50"))
        self.assertEqual(pct_change(Decimal("50"), Decimal("100")), Decimal("-50"))


if __name__ == "__main__":
    unittest.main()
