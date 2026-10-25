import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_connection import render, run_checks  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FAKE = [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")]
SECRET = "SYNTH-DEV-TOKEN-should-never-print"


class Workspace:
    """A temporary repo folder with a .mcp.json and a credentials file outside it."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        self.creds = base / "creds" / "application_default_credentials.json"
        self.creds.parent.mkdir()
        self.write_creds({"type": "authorized_user", "client_id": "synthetic", "client_secret": "synthetic",
                          "refresh_token": "synthetic"})

    def write_creds(self, data, mode=0o600):
        self.creds.write_text(data if isinstance(data, str) else json.dumps(data))
        os.chmod(self.creds, mode)

    def write_config(self, env=None, command=None):
        env = {"GOOGLE_APPLICATION_CREDENTIALS": str(self.creds), "GOOGLE_PROJECT_ID": "synthetic-project",
               **(env or {})}
        cmd = command or FAKE
        (self.repo / ".mcp.json").write_text(json.dumps(
            {"mcpServers": {"google-ads-mcp": {"command": cmd[0], "args": cmd[1:], "env": env}}}))

    def status(self, checks, name):
        return next(c for c in checks if c.name == name).status

    def close(self):
        self.tmp.cleanup()


class StaticChecksTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.close()

    def test_all_good_static(self):
        self.ws.write_config()
        checks = run_checks(self.ws.repo)
        self.assertEqual([c.name for c in checks if c.status == "fail"], [])
        self.assertEqual(self.ws.status(checks, "credentials file"), "ok")

    def test_missing_config_fails_with_fix(self):
        checks = run_checks(self.ws.repo)
        cfg = next(c for c in checks if c.name == ".mcp.json")
        self.assertEqual(cfg.status, "fail")
        self.assertIn("docs/mcp-setup.md", cfg.fix)

    def test_placeholder_fails(self):
        self.ws.write_config({"GOOGLE_PROJECT_ID": "YOUR_PROJECT_ID"})
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), ".mcp.json"), "fail")

    def test_missing_credentials_file_fails(self):
        self.ws.write_config({"GOOGLE_APPLICATION_CREDENTIALS": str(self.ws.creds) + ".missing"})
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials file"), "fail")

    def test_invalid_credentials_json_fails(self):
        self.ws.write_creds("not json")
        self.ws.write_config()
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials file"), "fail")

    def test_unknown_credentials_type_fails(self):
        self.ws.write_creds({"type": "mystery"})
        self.ws.write_config()
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials file"), "fail")

    def test_user_credentials_without_refresh_token_fail(self):
        self.ws.write_creds({"type": "authorized_user", "client_id": "x"})
        self.ws.write_config()
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials file"), "fail")

    @unittest.skipIf(os.name == "nt", "POSIX permissions only")
    def test_readable_by_others_warns(self):
        self.ws.write_creds({"type": "authorized_user", "refresh_token": "x"}, mode=0o644)
        self.ws.write_config()
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials permissions"), "warn")

    def test_credentials_inside_repo_warns(self):
        inside = self.ws.repo / "creds.json"
        inside.write_text(json.dumps({"type": "authorized_user", "refresh_token": "x"}))
        os.chmod(inside, 0o600)
        self.ws.write_config({"GOOGLE_APPLICATION_CREDENTIALS": str(inside)})
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "credentials location"), "warn")

    def test_bad_login_customer_id_fails(self):
        self.ws.write_config({"GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123-45"})
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "login customer ID"), "fail")

    def test_secrets_never_printed(self):
        self.ws.write_config({"GOOGLE_ADS_DEVELOPER_TOKEN": SECRET})
        checks = run_checks(self.ws.repo)
        self.assertEqual(self.ws.status(checks, "developer token"), "ok")
        self.assertNotIn(SECRET, render(checks))
        self.assertNotIn("synthetic-refresh", render(checks))

    def test_missing_launcher_fails(self):
        self.ws.write_config(command=["definitely-not-a-real-launcher-synth", "run"])
        self.assertEqual(self.ws.status(run_checks(self.ws.repo), "server launcher"), "fail")


class LiveChecksTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.close()

    def test_live_server_contract_ok(self):
        self.ws.write_config({"FAKE_FIXTURE": str(FIX / "synthetic_accessible_customers.json")})
        checks = run_checks(self.ws.repo, live=True, customer_id="900-000-0001")
        self.assertEqual(self.ws.status(checks, "server starts"), "ok")
        self.assertEqual(self.ws.status(checks, "search tool contract"), "ok")
        self.assertEqual(self.ws.status(checks, "customer access"), "ok")

    def test_customer_not_accessible_fails(self):
        self.ws.write_config({"FAKE_FIXTURE": str(FIX / "synthetic_accessible_customers.json")})
        checks = run_checks(self.ws.repo, live=True, customer_id="9000000099")
        self.assertEqual(self.ws.status(checks, "customer access"), "fail")

    def test_server_crash_fails_without_leaking_stderr(self):
        self.ws.write_config({"FAKE_FIXTURE": str(FIX / "synthetic_accessible_customers.json"),
                              "FAKE_MODE": "exit_on_call"})
        checks = run_checks(self.ws.repo, live=True, customer_id="9000000001")
        self.assertEqual(self.ws.status(checks, "customer access"), "fail")
        self.assertNotIn("SYNTH_STDERR_SECRET", render(checks))

    def test_live_skipped_when_static_fails(self):
        checks = run_checks(self.ws.repo, live=True)
        self.assertEqual(self.ws.status(checks, "server starts"), "skipped")


class RenderTest(unittest.TestCase):
    def test_render_summarises(self):
        ws = Workspace()
        try:
            out = render(run_checks(ws.repo))
            self.assertIn("FAIL", out)
            self.assertIn("Next step", out)
        finally:
            ws.close()


if __name__ == "__main__":
    unittest.main()
