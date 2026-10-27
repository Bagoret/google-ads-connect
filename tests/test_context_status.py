import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.onboarding.context import readiness_markdown, scan_context  # noqa: E402

SAMPLE_BUSINESS = """# Business context
## Identity and market
| Field | Value | Source | As of |
|---|---|---|---|
| Website URL | https://example.invalid | user | 2026-10-25 |
| Account currency | UNKNOWN | | |
"""
SAMPLE_CALENDAR = """# Commercial calendar
## Seasonality
| Field | Value | Source |
|---|---|---|
| Peak months observed (with data source) | UNKNOWN | |
"""
SAMPLE_MEASUREMENT = """# Measurement
## Conversion actions
| Conversion action | Source | Primary or secondary |
|---|---|---|
| UNKNOWN | | |
"""


class ContextStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "business.md").write_text(SAMPLE_BUSINESS)
        (d / "commercial-calendar.md").write_text(SAMPLE_CALENDAR)
        (d / "measurement.md").write_text(SAMPLE_MEASUREMENT)
        self.fields = scan_context(d)

    def tearDown(self):
        self.tmp.cleanup()

    def by_name(self, name):
        return [f for f in self.fields if f.name.startswith(name)]

    def test_unknown_fields_found_filled_ignored(self):
        self.assertTrue(self.by_name("Account currency"))
        self.assertFalse(self.by_name("Website URL"))
        self.assertFalse(self.by_name("Field"))  # header rows are not fields

    def test_currency_is_blocking(self):
        self.assertTrue(self.by_name("Account currency")[0].blocking)

    def test_calendar_is_optional(self):
        self.assertFalse(self.by_name("Peak months")[0].blocking)

    def test_unknown_table_row_named_after_section_and_blocking(self):
        f = self.by_name("Conversion actions")
        self.assertTrue(f and f[0].blocking)

    def test_readiness_never_asks_for_credentials(self):
        md = readiness_markdown(self.fields, mcp_configured=False, snapshots=[])
        self.assertIn("Blockers", md)
        self.assertIn("Account currency", md)
        self.assertNotIn("paste your", md.lower())
        self.assertIn("never share", md.lower())


if __name__ == "__main__":
    unittest.main()
