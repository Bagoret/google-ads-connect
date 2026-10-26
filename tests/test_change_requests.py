import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from change_requests import load_requests, main  # noqa: E402

BUDGET = ["--operation", "set_campaign_budget", "--customer-id", "900-000-0000",
          "--param", "campaign_id=9000000001", "--param", "budget_id=5000000001",
          "--param", "amount_micros_before=20000000", "--param", "amount_micros_after=25000000",
          "--rationale", "SYNTHETIC test rationale", "--evidence", "outputs/synthetic/report.md"]


class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.requests = base / "requests"
        self.log = base / "change-log.md"
        self.log.write_text("| header |\n|---|\n")
        self.config = base / "execution.json"
        self.config.write_text(json.dumps({"writes_enabled": False, "executor": "disabled"}))

    def run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main([*args, "--requests-dir", str(self.requests), "--change-log", str(self.log),
                         "--config", str(self.config)])
        return code, out.getvalue()

    def propose(self, *extra):
        code, out = self.run("propose", *BUDGET, *extra)
        assert code == 0, out
        cid = re.search(r"id: (\S+)", out).group(1)
        fp = re.search(r"fingerprint: ([0-9a-f]{64})", out).group(1)
        return cid, fp


class ProposeTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.tmp.cleanup()

    def test_propose_saves_and_prints_fingerprint(self):
        cid, fp = self.env.propose()
        self.assertTrue(cid.startswith("CR-"))
        reqs = load_requests(self.env.requests)
        self.assertEqual(reqs[cid].status, "proposed")
        self.assertEqual(reqs[cid].fingerprint(), fp)
        self.assertEqual(reqs[cid].customer_id, "9000000000")
        self.assertEqual(reqs[cid].params["amount_micros_after"], 25000000)

    def test_invalid_operation_writes_nothing(self):
        code, _ = self.env.run("propose", "--operation", "delete_account", "--customer-id", "9000000000",
                               "--rationale", "x", "--evidence", "y")
        self.assertEqual(code, 2)
        self.assertFalse(self.env.requests.exists() and any(self.env.requests.iterdir()))


class ApproveRejectTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.tmp.cleanup()

    def test_wrong_fingerprint_refused(self):
        cid, _ = self.env.propose()
        code, _ = self.env.run("approve", "--id", cid, "--approver", "Owner", "--fingerprint", "0" * 64)
        self.assertEqual(code, 2)
        self.assertEqual(load_requests(self.env.requests)[cid].status, "proposed")
        self.assertNotIn(cid, self.env.log.read_text())

    def test_approve_records_change_log_and_keeps_history(self):
        cid, fp = self.env.propose()
        code, _ = self.env.run("approve", "--id", cid, "--approver", "Owner", "--fingerprint", fp)
        self.assertEqual(code, 0)
        cr = load_requests(self.env.requests)[cid]
        self.assertEqual(cr.status, "approved")
        self.assertIn(cid, self.env.log.read_text())
        self.assertEqual(len(list(self.env.requests.glob(f"{cid}_*.json"))), 2)  # never overwritten

    def test_reject(self):
        cid, _ = self.env.propose()
        code, _ = self.env.run("reject", "--id", cid, "--actor", "Owner", "--note", "not now")
        self.assertEqual(code, 0)
        self.assertEqual(load_requests(self.env.requests)[cid].status, "rejected")
        self.assertNotIn(cid, self.env.log.read_text())

    def test_unknown_id(self):
        code, _ = self.env.run("reject", "--id", "CR-NOPE", "--actor", "x")
        self.assertEqual(code, 2)


class StatusPageTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.tmp.cleanup()

    def page(self):
        code, out = self.env.run("view")
        self.assertEqual(code, 0)
        return (self.env.requests / "status.html").read_text(encoding="utf-8")

    def test_empty_state(self):
        html = self.page()
        self.assertIn("No change requests yet", html)
        self.assertIn("Writes are disabled", html)

    def test_counts_badges_and_self_contained(self):
        a, fa = self.env.propose()
        b, _ = self.env.propose()
        self.env.run("approve", "--id", a, "--approver", "Owner", "--fingerprint", fa)
        self.env.run("reject", "--id", b, "--actor", "Owner")
        self.env.propose()
        html = self.page()
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html))
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertRegex(html, r'tile-label">Proposed</div><div class="tile-value">1<')
        self.assertRegex(html, r'tile-label">Approved</div><div class="tile-value">1<')
        self.assertRegex(html, r'tile-label">Rejected</div><div class="tile-value">1<')
        self.assertIn("20000000 → 25000000", html)

    def test_change_summary_for_negatives(self):
        self.env.run("propose", "--operation", "add_campaign_negative_keyword", "--customer-id", "9000000000",
                     "--param", "campaign_id=9000000002", "--param", "text=gratuit", "--param", "match_type=PHRASE",
                     "--rationale", "SYNTHETIC", "--evidence", "x")
        self.assertIn("add negative &quot;gratuit&quot; (PHRASE)", self.page())

    def test_edited_after_approval_shows_void(self):
        cid, fp = self.env.propose()
        self.env.run("approve", "--id", cid, "--approver", "Owner", "--fingerprint", fp)
        latest = max(self.env.requests.glob(f"{cid}_*.json"))
        data = json.loads(latest.read_text())
        data["params"]["amount_micros_after"] = 99000000
        latest.write_text(json.dumps(data))
        html = self.page()
        row = re.search(rf'<li class="request" data-request="{cid}">.*?<details', html, re.S).group(0)
        self.assertIn("Approval void", row)

    def test_untrusted_text_escaped(self):
        self.env.propose("--rationale", "<script>alert(1)</script>")
        html = self.page()
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)", html)

    def test_writes_enabled_is_shown_loudly(self):
        self.env.config.write_text(json.dumps({"writes_enabled": True, "executor": "disabled"}))
        self.assertIn("writes_enabled is ON", self.page())


if __name__ == "__main__":
    unittest.main()
