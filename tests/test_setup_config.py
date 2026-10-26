import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from setup_config import SetupError, check_client_file, main, normalise_customer_id, server_entry, write_desktop, write_mcp_json  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.creds = self.base / "home" / ".config" / "gcloud" / "application_default_credentials.json"
        self.creds.parent.mkdir(parents=True)
        self.creds.write_text(json.dumps({"type": "authorized_user", "refresh_token": "SYNTH"}))
        self.pipx = self.base / "bin" / "pipx"
        self.pipx.parent.mkdir()
        self.pipx.write_text("#!/bin/sh\n")

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, **over):
        args = {"pipx": str(self.pipx), "credentials": str(self.creds), "project_id": "shaped-buttress-512811-c9"}
        args.update(over)
        return server_entry(**args)


class CustomerIdTest(unittest.TestCase):
    def test_dashes_and_spaces_removed(self):
        self.assertEqual(normalise_customer_id("123-456-7890"), "1234567890")
        self.assertEqual(normalise_customer_id(" 123 456 7890 "), "1234567890")

    def test_wrong_length_or_letters_rejected(self):
        for bad in ("12345", "123-456-78901", "abc-def-ghij", ""):
            with self.assertRaises(SetupError):
                normalise_customer_id(bad)


class ServerEntryTest(Fixture):
    def test_entry_is_pinned_and_absolute(self):
        e = self.entry()
        self.assertEqual(e["command"], str(self.pipx))
        self.assertEqual(e["args"], ["run", "--spec", "google-ads-mcp==0.0.5", "google-ads-mcp"])
        self.assertEqual(e["env"], {"GOOGLE_APPLICATION_CREDENTIALS": str(self.creds),
                                    "GOOGLE_PROJECT_ID": "shaped-buttress-512811-c9"})

    def test_manager_id_added_only_when_given(self):
        self.assertEqual(self.entry(login_customer_id="111-222-3333")["env"]["GOOGLE_ADS_LOGIN_CUSTOMER_ID"], "1112223333")

    def test_bad_project_id_rejected(self):
        for bad in ("YOUR_PROJECT_ID", "Shaped", "a", "1abcdef", "abcdef-", "has space here"):
            with self.assertRaises(SetupError, msg=bad):
                self.entry(project_id=bad)

    def test_missing_files_rejected(self):
        with self.assertRaises(SetupError):
            self.entry(credentials=str(self.base / "nope.json"))
        with self.assertRaises(SetupError):
            self.entry(pipx="pipx")  # must be an absolute path

    def test_credentials_inside_repo_rejected(self):
        inside = self.repo / "creds.json"
        inside.write_text("{}")
        with self.assertRaises(SetupError):
            server_entry(pipx=str(self.pipx), credentials=str(inside), project_id="my-project-1", repo=self.repo)


class ClientFileTest(Fixture):
    def write(self, data):
        path = self.base / "client_secret.json"
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_desktop_client_accepted(self):
        check_client_file(self.write({"installed": {"client_id": "synth.apps.googleusercontent.com"}}))

    def test_web_client_and_junk_rejected(self):
        for bad in ({"web": {"client_id": "x"}}, {"installed": {}}, [], "not json"):
            with self.assertRaises(SetupError):
                check_client_file(self.write(bad))

    def test_error_never_echoes_contents(self):
        path = self.write({"web": {"client_id": "x", "client_secret": "SYNTH_SECRET_VALUE"}})
        with self.assertRaises(SetupError) as ctx:
            check_client_file(path)
        self.assertNotIn("SYNTH_SECRET_VALUE", str(ctx.exception))


class McpJsonTest(Fixture):
    def test_written_private_and_valid(self):
        path = write_mcp_json(self.repo, self.entry())
        data = json.loads(path.read_text())
        self.assertEqual(list(data["mcpServers"]), ["google-ads-mcp"])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_file_kept_unless_replace_then_backed_up(self):
        target = self.repo / ".mcp.json"
        target.write_text('{"old": true}')
        with self.assertRaises(SetupError):
            write_mcp_json(self.repo, self.entry())
        self.assertEqual(target.read_text(), '{"old": true}')
        write_mcp_json(self.repo, self.entry(), replace=True)
        backups = list(self.repo.glob(".mcp.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '{"old": true}')
        self.assertIn("mcpServers", target.read_text())

    def test_no_developer_token_written(self):
        text = write_mcp_json(self.repo, self.entry()).read_text()
        self.assertNotIn("DEVELOPER_TOKEN", text)


class DesktopTest(Fixture):
    def cfg(self):
        return self.base / "Claude" / "claude_desktop_config.json"

    def test_creates_file_when_missing(self):
        write_desktop(self.cfg(), self.entry())
        self.assertIn("google-ads-mcp", json.loads(self.cfg().read_text())["mcpServers"])

    def test_keeps_other_servers_and_settings_and_backs_up(self):
        self.cfg().parent.mkdir(parents=True)
        original = {"mcpServers": {"other": {"command": "x"}}, "globalShortcut": "Cmd+K"}
        self.cfg().write_text(json.dumps(original))
        write_desktop(self.cfg(), self.entry())
        data = json.loads(self.cfg().read_text())
        self.assertEqual(data["mcpServers"]["other"], {"command": "x"})
        self.assertEqual(data["globalShortcut"], "Cmd+K")
        self.assertIn("google-ads-mcp", data["mcpServers"])
        backups = list(self.cfg().parent.glob("claude_desktop_config.json.bak-*"))
        self.assertEqual(json.loads(backups[0].read_text()), original)

    def test_existing_different_entry_needs_replace(self):
        self.cfg().parent.mkdir(parents=True)
        self.cfg().write_text(json.dumps({"mcpServers": {"google-ads-mcp": {"command": "old"}}}))
        with self.assertRaises(SetupError):
            write_desktop(self.cfg(), self.entry())
        write_desktop(self.cfg(), self.entry(), replace=True)
        self.assertEqual(json.loads(self.cfg().read_text())["mcpServers"]["google-ads-mcp"]["command"], str(self.pipx))

    def test_same_entry_is_a_no_op(self):
        write_desktop(self.cfg(), self.entry())
        self.assertFalse(write_desktop(self.cfg(), self.entry()))
        self.assertEqual(list(self.cfg().parent.glob("*.bak-*")), [])

    def test_invalid_json_left_untouched(self):
        self.cfg().parent.mkdir(parents=True)
        self.cfg().write_text("{not json")
        with self.assertRaises(SetupError):
            write_desktop(self.cfg(), self.entry())
        self.assertEqual(self.cfg().read_text(), "{not json")


class CliTest(Fixture):
    def test_cli_writes_mcp_json_and_reports_errors(self):
        common = ["--pipx", str(self.pipx), "--credentials", str(self.creds), "--project-id", "my-project-1"]
        self.assertEqual(main(["mcp-json", "--repo", str(self.repo), *common]), 0)
        self.assertTrue((self.repo / ".mcp.json").exists())
        self.assertEqual(main(["mcp-json", "--repo", str(self.repo), *common]), 2)  # exists, no --replace
        self.assertEqual(main(["customer-id", "123-456-7890"]), 0)
        self.assertEqual(main(["customer-id", "12"]), 2)
        self.assertEqual(main(["project-id", "shaped-buttress-512811-c9"]), 0)
        self.assertEqual(main(["project-id", "YOUR_PROJECT_ID"]), 2)


if __name__ == "__main__":
    unittest.main()
