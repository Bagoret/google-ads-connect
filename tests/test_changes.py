import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gads.changes import (OPERATIONS, ChangeRequest, DisabledExecutor, IllegalTransition, WritesDisabled,  # noqa: E402
                          approve, execute_change, record_approved, save_request, transition, validate_change)

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def cr(**over):
    base = dict(id="CR-SYNTH-001", customer_id="9000000000", operation="set_campaign_budget",
                params={"campaign_id": "9000000001", "budget_id": "5000000001",
                        "amount_micros_before": 20000000, "amount_micros_after": 25000000},
                rationale="SYNTHETIC", evidence="outputs/synthetic/report.md")
    base.update(over)
    return ChangeRequest(**base)


class ValidationTest(unittest.TestCase):
    def test_valid_request_has_no_errors(self):
        self.assertEqual(validate_change(cr()), [])

    def test_unknown_operation_invalid(self):
        self.assertTrue(validate_change(cr(operation="delete_account", params={})))

    def test_missing_and_extra_params(self):
        errors = validate_change(cr(params={"campaign_id": "1", "surprise": 1}))
        self.assertTrue(any("missing" in e for e in errors))
        self.assertTrue(any("unexpected" in e for e in errors))

    def test_bad_match_type(self):
        c = cr(operation="add_campaign_negative_keyword",
               params={"campaign_id": "9000000001", "text": "gratuit", "match_type": "FUZZY"})
        self.assertTrue(any("match_type" in e for e in validate_change(c)))

    def test_bad_customer_id_and_noop(self):
        c = cr(customer_id="123", params={"campaign_id": "9000000001", "budget_id": "5000000001",
                                          "amount_micros_before": 1, "amount_micros_after": 1})
        errors = validate_change(c)
        self.assertTrue(any("customer_id" in e for e in errors))
        self.assertTrue(any("before" in e for e in errors))

    def test_operations_catalog(self):
        self.assertIn("pause_campaign", OPERATIONS)
        self.assertEqual(OPERATIONS["pause_keyword"], frozenset({"ad_group_id", "criterion_id"}))


class ApprovalTest(unittest.TestCase):
    def test_approval_requires_matching_fingerprint(self):
        with self.assertRaises(ValueError):
            approve(cr(), "owner", "deadbeef", NOW)

    def test_approval_requires_approver(self):
        c = cr()
        with self.assertRaises(ValueError):
            approve(c, "  ", c.fingerprint(), NOW)

    def test_invalid_request_cannot_be_approved(self):
        c = cr(operation="delete_account", params={})
        with self.assertRaises(ValueError):
            approve(c, "owner", c.fingerprint(), NOW)

    def test_approve_records_history(self):
        c = cr()
        approve(c, "owner", c.fingerprint(), NOW)
        self.assertEqual(c.status, "approved")
        self.assertEqual(c.approval["fingerprint"], c.fingerprint())
        self.assertEqual(c.history[-1]["to"], "approved")

    def test_illegal_transition(self):
        with self.assertRaises(IllegalTransition):
            transition(cr(), "executed", "x", NOW)


class ExecutionTest(unittest.TestCase):
    def approved(self):
        c = cr()
        approve(c, "owner", c.fingerprint(), NOW)
        return c

    def test_edit_after_approval_blocks_execution(self):
        c = self.approved()
        c.params["amount_micros_after"] = 999
        with self.assertRaises(PermissionError):
            execute_change(c, DisabledExecutor(), {"writes_enabled": True})

    def test_writes_disabled_by_config_even_if_approved(self):
        with self.assertRaises(WritesDisabled):
            execute_change(self.approved(), DisabledExecutor(), {"writes_enabled": False})

    def test_missing_config_flag_means_disabled(self):
        with self.assertRaises(WritesDisabled):
            execute_change(self.approved(), DisabledExecutor(), {})

    def test_disabled_executor_always_refuses(self):
        with self.assertRaises(WritesDisabled):
            execute_change(self.approved(), DisabledExecutor(), {"writes_enabled": True})

    def test_proposed_cannot_be_executed_or_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "change-log.md"
            log.write_text("| header |\n")
            with self.assertRaises(PermissionError):
                execute_change(cr(), DisabledExecutor(), {"writes_enabled": True})
            with self.assertRaises(PermissionError):
                record_approved(cr(), log)

    def test_record_approved_appends_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "change-log.md"
            log.write_text("| header |\n")
            record_approved(self.approved(), log)
            text = log.read_text()
            self.assertIn("CR-SYNTH-001", text)
            self.assertIn("set_campaign_budget", text)
            self.assertIn("owner", text)

    def test_save_request_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cr()
            p1 = save_request(c, Path(tmp))
            approve(c, "owner", c.fingerprint(), NOW)
            p2 = save_request(c, Path(tmp))
            self.assertNotEqual(p1, p2)
            self.assertEqual(ChangeRequest.from_dict(json.loads(p2.read_text())).status, "approved")


class ShippedConfigTest(unittest.TestCase):
    def test_shipped_config_has_writes_disabled(self):
        cfg = json.loads((ROOT / "config" / "execution.json").read_text())
        self.assertIs(cfg["writes_enabled"], False)
        self.assertEqual(cfg["executor"], "disabled")


if __name__ == "__main__":
    unittest.main()
