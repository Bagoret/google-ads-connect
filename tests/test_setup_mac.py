"""Runs scripts/setup_mac.sh end to end against stub brew/pipx/gcloud in a throwaway HOME and repo copy.

The stub pipx starts tests/fake_mcp_server.py, so the script's real connection check runs too.
Not covered here: real Homebrew installs, the real Google sign-in, and real macOS paths.
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
TOOLS = ["bash", "ls", "mv", "chmod", "mkdir", "head", "sed", "dirname", "cat", "rm", "env", "uname", "cp"]

GCLOUD = """#!/bin/sh
printf '%s\\n' "$*" >> "$HOME/gcloud-args.txt"
mkdir -p "$HOME/.config/gcloud"
printf '{"type": "authorized_user", "client_id": "x", "client_secret": "SYNTH_SECRET_VALUE", "refresh_token": "SYNTH_REFRESH"}' \\
  > "$HOME/.config/gcloud/application_default_credentials.json"
"""
PIPX = f"#!/bin/sh\nexec {sys.executable} {ROOT / 'tests' / 'fake_mcp_server.py'}\n"
BREW = """#!/bin/sh
printf '%s\\n' "$*" >> "$HOME/brew-args.txt"
case "$*" in
  *gcloud-cli*) cp "$STUB_SRC/gcloud" "$STUB_BIN/gcloud" ;;
  *pipx*) cp "$STUB_SRC/pipx" "$STUB_BIN/pipx" ;;
esac
"""


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
class SetupMacTest(unittest.TestCase):
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
        for name, body in (("gcloud", GCLOUD), ("pipx", PIPX), ("brew", BREW)):
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

    def run_script(self, answers, *args, uname="Darwin"):
        env = {"HOME": str(self.home), "PATH": str(self.bin), "STUB_BIN": str(self.bin), "STUB_SRC": str(self.src),
               "FAKE_FIXTURE": str(FIX / "synthetic_accessible_customers.json")}
        if uname:
            env["SETUP_UNAME"] = uname
        return subprocess.run([str(self.bin / "bash"), str(self.repo / "scripts" / "setup_mac.sh"), *args],
                              input="\n".join(answers) + "\n", capture_output=True, text=True, env=env, timeout=120)

    def test_happy_path_writes_private_config_and_desktop_entry(self):
        self.install("pipx", "gcloud")
        self.client()
        # answers: move client file, customer ID, no manager, add to Claude Desktop
        r = self.run_script(["y", "900-000-0001", "", "y"], "--project-id", "shaped-buttress-512811-c9")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("Connection check passed", out)
        client = self.home / ".config" / "google-ads-os" / "client_secret.json"
        self.assertEqual(stat.S_IMODE(client.stat().st_mode), 0o600)
        self.assertFalse(list((self.home / "Downloads").iterdir()))
        args = (self.home / "gcloud-args.txt").read_text()
        self.assertIn("auth application-default login", args)
        self.assertIn("auth/adwords", args)
        self.assertIn(f"--client-id-file={client}", args)
        mcp = json.loads((self.repo / ".mcp.json").read_text())["mcpServers"]["google-ads-mcp"]
        self.assertEqual(mcp["command"], str(self.bin / "pipx"))
        self.assertEqual(mcp["env"]["GOOGLE_PROJECT_ID"], "shaped-buttress-512811-c9")
        self.assertNotIn("GOOGLE_ADS_LOGIN_CUSTOMER_ID", mcp["env"])
        desktop = self.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        self.assertEqual(json.loads(desktop.read_text())["mcpServers"]["google-ads-mcp"], mcp)
        for secret in ("SYNTH_SECRET_VALUE", "SYNTH_REFRESH", "SYNTH_CLIENT_SECRET"):
            self.assertNotIn(secret, out)
        self.assertFalse((self.home / "brew-args.txt").exists())

    def test_declined_install_stops_without_running_brew(self):
        self.install("gcloud")
        r = self.run_script(["n"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("pipx is required", r.stderr)
        self.assertFalse((self.home / "brew-args.txt").exists())

    def test_accepted_install_uses_the_gcloud_cli_cask(self):
        self.install("pipx", "brew")
        self.client()
        r = self.run_script(["y", "y", "9000000001", "", "n"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / "brew-args.txt").read_text().strip(), "install --cask gcloud-cli")

    def test_web_client_rejected_before_sign_in(self):
        self.install("pipx", "gcloud")
        self.client({"web": {"client_id": "x"}})
        r = self.run_script(["y"], "--project-id", "my-project-1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Desktop app", r.stderr)
        self.assertFalse((self.home / "gcloud-args.txt").exists())

    def test_bad_project_id_stops_before_sign_in(self):
        self.install("pipx", "gcloud")
        self.client()
        r = self.run_script(["y"], "--project-id", "YOUR_PROJECT_ID")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.home / "gcloud-args.txt").exists())

    def test_existing_mcp_json_kept_when_declined(self):
        self.install("pipx", "gcloud")
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
