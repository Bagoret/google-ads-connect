"""Runs scripts/setup_mac.sh end to end against stub brew/gcloud in a throwaway HOME and repo copy.

Google's server is installed for real into a venv, but from a local SYNTHETIC wheel (tests/fake_wheel.py,
no network) whose google-ads-mcp command runs tests/fake_mcp_server.py, so the real connection check runs too.
Not covered here: real Homebrew installs, the real Google sign-in, real macOS paths and macOS's Python quirks.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_wheel  # noqa: E402
from setup_config import find_pip_wheel  # noqa: E402

CAN_BUILD_VENV = (3, 10) <= sys.version_info[:2] <= (3, 13) and find_pip_wheel(sys.executable) is not None
TOOLS = ["bash", "ls", "mv", "chmod", "mkdir", "head", "sed", "dirname", "cat", "rm", "env", "uname", "cp"]

GCLOUD = """#!/bin/sh
printf '%s\\n' "$*" >> "$HOME/gcloud-args.txt"
mkdir -p "$HOME/.config/gcloud"
printf '{"type": "authorized_user", "client_id": "x", "client_secret": "SYNTH_SECRET_VALUE", "refresh_token": "SYNTH_REFRESH"}' \\
  > "$HOME/.config/gcloud/application_default_credentials.json"
"""
BREW = """#!/bin/sh
printf '%s\\n' "$*" >> "$HOME/brew-args.txt"
case "$*" in
  *gcloud-cli*) cp "$STUB_SRC/gcloud" "$STUB_BIN/gcloud" ;;
esac
"""
OLD_PIPX_ENTRY = {"command": "/opt/homebrew/bin/pipx", "args": ["run", "--spec", "google-ads-mcp==0.0.5", "google-ads-mcp"],
                  "env": {"GOOGLE_PROJECT_ID": "my-project-1"}}


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
@unittest.skipUnless(CAN_BUILD_VENV, "needs a Python 3.10-3.13 with a bundled pip wheel")
class SetupMacTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One prebuilt server venv, shared by tests that are not about installing the server."""
        cls.shared = tempfile.TemporaryDirectory()
        cls.wheels = Path(cls.shared.name) / "wheels"
        fake_wheel.build(cls.wheels)
        cls.shared_venv = Path(cls.shared.name) / "mcp-venv"
        env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(cls.wheels)}
        subprocess.run([sys.executable, str(ROOT / "scripts" / "setup_config.py"), "server-venv", "--python",
                        sys.executable, "--venv", str(cls.shared_venv)], env=env, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        (self.home / "Downloads").mkdir(parents=True)
        self.repo = base / "repo"
        for d in ("scripts", "config", "queries"):
            shutil.copytree(ROOT / d, self.repo / d, ignore=shutil.ignore_patterns("__pycache__"))
        self.bin = base / "bin"
        self.src = base / "stubs"
        self.bin.mkdir()
        self.src.mkdir()
        for tool in TOOLS:
            os.symlink(shutil.which(tool), self.bin / tool)
        os.symlink(sys.executable, self.bin / "python3")
        for name, body in (("gcloud", GCLOUD), ("brew", BREW)):
            path = self.src / name
            path.write_text(body)
            path.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *names):
        for name in names:
            shutil.copy(self.src / name, self.bin / name)

    def client(self, data=None):
        data = data or {"installed": {"client_id": "synth.apps.googleusercontent.com", "client_secret": "SYNTH_CLIENT_SECRET"}}
        (self.home / "Downloads" / "client_secret_123.json").write_text(json.dumps(data))

    def run_script(self, answers, *args, uname="Darwin", shared_venv=True):
        env = {"HOME": str(self.home), "PATH": str(self.bin), "STUB_BIN": str(self.bin), "STUB_SRC": str(self.src),
               "FAKE_FIXTURE": str(FIX / "synthetic_accessible_customers.json"),
               "FAKE_SERVER": str(ROOT / "tests" / "fake_mcp_server.py"),
               "PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(self.wheels)}
        if shared_venv:
            env["GOOGLE_ADS_OS_VENV"] = str(self.shared_venv)
        if uname:
            env["SETUP_UNAME"] = uname
        return subprocess.run([str(self.bin / "bash"), str(self.repo / "scripts" / "setup_mac.sh"), *args],
                              input="\n".join(answers) + "\n", capture_output=True, text=True, env=env, timeout=120)

    def venv_exe(self):
        return self.home / ".local" / "share" / "google-ads-os" / "mcp-venv" / "bin" / "google-ads-mcp"

    def test_happy_path_writes_private_config_and_desktop_entry(self):
        self.install("gcloud")
        self.client()
        # answers: install the server, move client file, customer ID, no manager, add to Claude Desktop
        r = self.run_script(["y", "y", "900-000-0001", "", "y"], "--project-id", "shaped-buttress-512811-c9",
                            shared_venv=False)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("Connection check passed", out)
        self.assertTrue(os.access(self.venv_exe(), os.X_OK))
        client = self.home / ".config" / "google-ads-os" / "client_secret.json"
        self.assertEqual(stat.S_IMODE(client.stat().st_mode), 0o600)
        self.assertFalse(list((self.home / "Downloads").iterdir()))
        args = (self.home / "gcloud-args.txt").read_text()
        self.assertIn("auth application-default login", args)
        self.assertIn("auth/adwords", args)
        self.assertIn(f"--client-id-file={client}", args)
        mcp = json.loads((self.repo / ".mcp.json").read_text())["mcpServers"]["google-ads-mcp"]
        self.assertEqual(mcp["command"], str(self.venv_exe()))
        self.assertEqual(mcp["args"], [])
        self.assertEqual(mcp["env"]["GOOGLE_PROJECT_ID"], "shaped-buttress-512811-c9")
        self.assertNotIn("GOOGLE_ADS_LOGIN_CUSTOMER_ID", mcp["env"])
        desktop = self.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        self.assertEqual(json.loads(desktop.read_text())["mcpServers"]["google-ads-mcp"], mcp)
        for secret in ("SYNTH_SECRET_VALUE", "SYNTH_REFRESH", "SYNTH_CLIENT_SECRET"):
            self.assertNotIn(secret, out)
        self.assertFalse((self.home / "brew-args.txt").exists())

    def test_rerun_keeps_everything_and_does_not_sign_in_again(self):
        self.install("gcloud")
        self.client()
        first = self.run_script(["y", "y", "9000000001", "", "y"], "--project-id", "shaped-buttress-512811-c9",
                                shared_venv=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        mcp_before = (self.repo / ".mcp.json").read_text()
        # answers: do not sign in again, customer ID, no manager, add to Claude Desktop (already there)
        r = self.run_script(["n", "9000000001", "", "y"], "--project-id", "shaped-buttress-512811-c9",
                            shared_venv=False)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("already installed", out)
        self.assertEqual((self.home / "gcloud-args.txt").read_text().count("application-default login"), 1)
        self.assertEqual((self.repo / ".mcp.json").read_text(), mcp_before)
        self.assertEqual(list(self.repo.glob(".mcp.json.bak-*")), [])
        desktop = self.home / "Library" / "Application Support" / "Claude"
        self.assertEqual(list(desktop.glob("*.bak-*")), [])

    def test_old_pipx_setup_is_backed_up_and_replaced(self):
        self.install("gcloud")
        self.client()
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"google-ads-mcp": OLD_PIPX_ENTRY}}))
        desktop = self.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(json.dumps({"mcpServers": {"google-ads-mcp": OLD_PIPX_ENTRY, "other": {"command": "x"}}}))
        # answers: move client, customer ID, no manager, replace .mcp.json, add to Desktop, replace Desktop entry
        r = self.run_script(["y", "9000000001", "", "y", "y", "y"], "--project-id", "my-project-1")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("pipx run", out)
        mcp = json.loads((self.repo / ".mcp.json").read_text())["mcpServers"]["google-ads-mcp"]
        self.assertEqual(mcp["command"], str(self.shared_venv / "bin" / "google-ads-mcp"))
        self.assertEqual(len(list(self.repo.glob(".mcp.json.bak-*"))), 1)
        data = json.loads(desktop.read_text())["mcpServers"]
        self.assertEqual(data["google-ads-mcp"], mcp)
        self.assertEqual(data["other"], {"command": "x"})
        self.assertEqual(len(list(desktop.parent.glob("*.bak-*"))), 1)

    def test_declined_server_install_stops_without_running_brew(self):
        self.install("gcloud")
        r = self.run_script(["n"], "--project-id", "my-project-1", shared_venv=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Google's server is required", r.stderr)
        self.assertFalse(self.venv_exe().exists())
        self.assertFalse((self.home / "brew-args.txt").exists())

    def test_declined_gcloud_install_stops_without_running_brew(self):
        r = self.run_script(["n"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Google Cloud CLI is required", r.stderr)
        self.assertFalse((self.home / "brew-args.txt").exists())

    def test_accepted_install_uses_the_gcloud_cli_cask(self):
        self.install("brew")
        self.client()
        r = self.run_script(["y", "y", "9000000001", "", "n"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / "brew-args.txt").read_text().strip(), "install --cask gcloud-cli")

    def test_web_client_rejected_before_sign_in(self):
        self.install("gcloud")
        self.client({"web": {"client_id": "x"}})
        r = self.run_script(["y"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Desktop app", r.stderr)
        self.assertFalse((self.home / "gcloud-args.txt").exists())

    def test_web_client_in_downloads_is_not_moved(self):
        self.install("gcloud")
        self.client({"web": {"client_id": "x"}})
        r = self.run_script(["y"], "--project-id", "my-project-1")  # even if the user would say yes
        self.assertEqual(r.returncode, 2)
        self.assertTrue((self.home / "Downloads" / "client_secret_123.json").exists())
        self.assertFalse((self.home / ".config" / "google-ads-os" / "client_secret.json").exists())

    def test_project_id_flag_without_value_explains(self):
        r = self.run_script([], "--project-id")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs a value", r.stderr)

    def test_bad_project_id_stops_before_sign_in(self):
        self.install("gcloud")
        self.client()
        r = self.run_script(["y"], "--project-id", "YOUR_PROJECT_ID")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.home / "gcloud-args.txt").exists())

    def test_existing_mcp_json_kept_when_declined(self):
        self.install("gcloud")
        self.client()
        (self.repo / ".mcp.json").write_text('{"mine": true}')
        r = self.run_script(["y", "9000000001", "", "n"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 2)
        self.assertEqual((self.repo / ".mcp.json").read_text(), '{"mine": true}')

    def test_refuses_to_run_outside_macos(self):
        r = self.run_script([], uname="Linux")
        self.assertEqual(r.returncode, 2)
        self.assertIn("for macOS", r.stderr)


if __name__ == "__main__":
    unittest.main()
