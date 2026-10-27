import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.core.logbook import RunLog, StopAnalysis  # noqa: E402
from gads.core.validate import check_date_coverage, check_single_currency, check_unique, partial_data_caveats  # noqa: E402

UTC = timezone.utc


class UniqueTest(unittest.TestCase):
    def test_duplicate_grain_key_stops(self):
        recs = [{"campaign_id": "9000000001", "date": date(2026, 10, 1)}] * 2
        with self.assertRaisesRegex(StopAnalysis, "9000000001"):
            check_unique(recs, ("campaign_id", "date"))

    def test_unique_ok(self):
        check_unique([{"campaign_id": "1", "date": date(2026, 10, 1)},
                      {"campaign_id": "1", "date": date(2026, 10, 2)}], ("campaign_id", "date"))


class CurrencyTest(unittest.TestCase):
    def test_mixed_currency_stops(self):
        with self.assertRaises(StopAnalysis):
            check_single_currency([{"currency": "EUR"}, {"currency": "USD"}], None)

    def test_expected_currency_mismatch_stops(self):
        with self.assertRaises(StopAnalysis):
            check_single_currency([{"currency": "USD"}], "EUR")

    def test_no_currency_anywhere_stops(self):
        with self.assertRaises(StopAnalysis):
            check_single_currency([{"cost": 1}], None)

    def test_expected_used_when_data_has_none(self):
        self.assertEqual(check_single_currency([{"cost": 1}], "EUR"), "EUR")

    def test_single_currency_returned(self):
        self.assertEqual(check_single_currency([{"currency": "EUR"}], "EUR"), "EUR")


class CoverageTest(unittest.TestCase):
    def test_missing_dates_warned(self):
        log = RunLog()
        missing = check_date_coverage([{"date": date(2026, 10, 1)}, {"date": date(2026, 10, 3)}],
                                      date(2026, 10, 1), date(2026, 10, 3), log)
        self.assertEqual(missing, [date(2026, 10, 2)])
        self.assertTrue(log.to_dict()["warnings"])


class PartialDataTest(unittest.TestCase):
    def test_partial_day_in_account_timezone(self):
        # 23:30 UTC on Oct 19 is already Oct 20 in Paris -> an Oct 20 end date is partial
        c = partial_data_caveats(date(2026, 10, 20), "Europe/Paris", None, datetime(2026, 10, 19, 23, 30, tzinfo=UTC))
        self.assertTrue(any("partial" in x for x in c))

    def test_future_end_is_partial(self):
        c = partial_data_caveats(date(2026, 10, 21), "Europe/Paris", 7, datetime(2026, 10, 19, 12, tzinfo=UTC))
        self.assertTrue(any("partial" in x for x in c))

    def test_unknown_lag_always_caveated(self):
        c = partial_data_caveats(date(2026, 10, 1), "Europe/Paris", None, datetime(2026, 10, 25, tzinfo=UTC))
        self.assertTrue(any("conversion delay unknown" in x for x in c))

    def test_known_lag_inside_window_caveated(self):
        c = partial_data_caveats(date(2026, 10, 20), "Europe/Paris", 7, datetime(2026, 10, 25, tzinfo=UTC))
        self.assertTrue(any("within the 7-day conversion delay" in x for x in c))

    def test_known_lag_outside_window_clean(self):
        self.assertEqual(partial_data_caveats(date(2026, 10, 1), "Europe/Paris", 7, datetime(2026, 10, 25, tzinfo=UTC)), [])


if __name__ == "__main__":
    unittest.main()
