import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.insights import build_facts, render_text, validate_insights  # noqa: E402
from weekly_review import build_parser, build_review  # noqa: E402
import dashboard  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
ARGS = ["--snapshot", str(FIX / "synthetic_weekly_two_weeks.json"), "--current", "2026-10-13:2026-10-19",
        "--previous", "2026-10-06:2026-10-12", "--expected-currency", "EUR", "--now", "2026-10-25T09:00:00+00:00"]


def facts():
    return build_facts(build_review(build_parser().parse_args(ARGS)))


def insight(**over):
    base = {"kind": "issue", "label": "Observed", "title": "Search ROAS fell",
            "text": "ROAS went from {{campaign.9000000002.previous.roas}} to {{campaign.9000000002.current.roas}}.",
            "entity_type": "campaign", "entity_id": "9000000002",
            "evidence": ["campaign.9000000002.current.roas"], "confidence": "medium"}
    base.update(over)
    return base


class FactsTest(unittest.TestCase):
    def test_facts_come_from_engine(self):
        f = facts()
        self.assertEqual(f["account.current.cost"], "273.00")
        self.assertEqual(f["account.current.roas"], "1.86")
        self.assertEqual(f["campaign.9000000002.current.roas"], "0.83")
        self.assertEqual(f["campaign.9000000003.current.cpa"], "N/A")
        self.assertEqual(f["campaign.9000000002.delta.cost"], "+50.0%")
        self.assertEqual(f["meta.currency"], "EUR")
        self.assertEqual(f["meta.current_period"], "2026-10-13 to 2026-10-19")

    def test_no_deltas_when_not_comparable(self):
        args = list(ARGS)
        args[args.index("2026-10-06:2026-10-12")] = "2026-10-07:2026-10-12"
        f = build_facts(build_review(build_parser().parse_args(args)))
        self.assertFalse([k for k in f if ".delta." in k])


class RenderTextTest(unittest.TestCase):
    def test_placeholders_substituted(self):
        out, problems = render_text("ROAS {{account.current.roas}}", facts())
        self.assertEqual((out, problems), ("ROAS 1.86", []))

    def test_unknown_placeholder_flagged(self):
        _, problems = render_text("ROAS {{account.current.nope}}", facts())
        self.assertTrue(any("unknown fact" in p for p in problems))

    def test_hand_typed_number_flagged(self):
        _, problems = render_text("ROAS dropped by 40%", facts())
        self.assertTrue(any("40%" in p for p in problems))

    def test_other_numerals_and_magnitude_words_flagged(self):
        for text in ("Cost doubled last week", "about twelve thousand euros", "a ½ share", "x² growth",
                     "ROAS fell by half", "a threefold increase"):
            _, problems = render_text(text, facts())
            self.assertTrue(problems, text)

    def test_short_numbers_are_never_treated_as_ids(self):
        f = {**facts(), "campaign.42.current.roas": "1.00"}
        _, problems = render_text("ROAS fell 42", f)
        self.assertTrue(problems)

    def test_entity_ids_and_period_dates_allowed(self):
        _, problems = render_text("Campaign 9000000002 between 2026-10-13 and 2026-10-19", facts())
        self.assertEqual(problems, [])


class ValidateTest(unittest.TestCase):
    def test_valid_insight_rendered(self):
        ok, rejected = validate_insights({"insights": [insight()]}, facts())
        self.assertEqual(rejected, [])
        self.assertEqual(ok[0]["text"], "ROAS went from 2.00 to 0.83.")
        self.assertEqual(ok[0]["evidence"], [{"key": "campaign.9000000002.current.roas", "value": "0.83"}])

    def test_rejections(self):
        cases = [insight(label="Fact"), insight(kind="idea"), insight(confidence="certain"),
                 insight(evidence=[]), insight(evidence=["campaign.1.current.roas"]),
                 insight(text="ROAS fell 58%"), insight(title="ROAS fell to {{bad.key}}")]
        ok, rejected = validate_insights({"insights": cases}, facts())
        self.assertEqual(ok, [])
        self.assertEqual(len(rejected), len(cases))
        self.assertTrue(all(r["reasons"] for r in rejected))

    def test_malformed_documents_rejected_not_crashing(self):
        cases = [insight(kind=["issue"]), insight(label={"x": 1}), insight(confidence=["low"]),
                 insight(entity_id=["9000000002"])]
        ok, rejected = validate_insights({"insights": cases}, facts())
        self.assertEqual((ok, len(rejected)), ([], len(cases)))
        for doc in ([insight()], "text", 5, {"insights": "x"}):
            ok, rejected = validate_insights(doc, facts())
            self.assertEqual(ok, [])
            self.assertTrue(rejected)

    def test_hypothesis_may_have_no_evidence_but_no_free_numbers(self):
        ok, _ = validate_insights({"insights": [insight(label="Hypothesis", evidence=[],
                                                        text="A competitor may have entered the auction.")]}, facts())
        self.assertEqual(len(ok), 1)


class DashboardSectionTest(unittest.TestCase):
    def test_ai_section_and_facts_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ins = Path(tmp) / "insights.json"
            ins.write_text(json.dumps({"insights": [
                insight(),
                insight(kind="opportunity", label="Recommendation", title="Shift <b>budget</b>",
                        text="Review budget for 9000000001 (ROAS {{campaign.9000000001.current.roas}}).",
                        entity_id="9000000001", evidence=["campaign.9000000001.current.roas"]),
                insight(text="Made-up 99% claim")]}))
            code = dashboard.main(ARGS + ["--insights", str(ins), "--out", tmp + "/o"])
            self.assertEqual(code, 0)
            out = next(Path(tmp, "o").iterdir())
            html = (out / "index.html").read_text()
            self.assertIn("AI analysis", html)
            self.assertIn("ROAS went from 2.00 to 0.83.", html)
            self.assertIn("Shift &lt;b&gt;budget&lt;/b&gt;", html)
            self.assertIn("Opportunity", html)
            self.assertIn("1 insight rejected", html)
            self.assertNotIn("Made-up 99% claim", html)
            self.assertEqual(json.loads((out / "facts.json").read_text())["facts"]["account.current.cost"], "273.00")

    def test_no_insights_section_says_how_to_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard.main(ARGS + ["--out", tmp])
            html = next(Path(tmp).glob("*/index.html")).read_text()
            self.assertIn("No AI analysis yet", html)



class CheckCliTest(unittest.TestCase):
    def test_cli_reports_and_exits_nonzero_on_rejections(self):
        import contextlib, io
        from check_insights import main as check_main
        with tempfile.TemporaryDirectory() as tmp:
            dashboard.main(ARGS + ["--out", tmp])
            facts_path = next(Path(tmp).glob("*/facts.json"))
            ins = Path(tmp) / "insights.json"
            ins.write_text(json.dumps({"insights": [insight(), insight(text="Invented 12%")]}))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = check_main(["--facts", str(facts_path), "--insights", str(ins)])
            self.assertEqual(code, 1)
            self.assertIn("1 verified, 1 rejected", out.getvalue())
            self.assertIn("number not from facts: 12%", out.getvalue())


if __name__ == "__main__":
    unittest.main()
