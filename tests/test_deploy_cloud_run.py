"""Runs scripts/deploy_cloud_run.sh against stub gcloud/git/curl and checks the commands it would send.

Not covered here: real Google Cloud behaviour (permissions, quotas, Cloud Build, Firestore locations).
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_cloud_run.sh"
CLIENT_ID = "123456789012-abcdef0123456789.apps.googleusercontent.com"
SECRET = "SYNTH_WEB_CLIENT_SECRET_VALUE"

GCLOUD = r"""#!/bin/bash
printf '%s\n' "$*" >> "$LOG"
if [ "$1 $2" = "secrets versions" ]; then printf 'STDIN=%s\n' "$(cat)" >> "$STDIN_LOG"; exit 0; fi
if [ "$1 $2" = "builds submit" ]; then cp "$3/Dockerfile" "$CAPTURE/Dockerfile.submitted"; exit 0; fi
case "$*" in
  "config get-value account") echo "synthetic-user@example.com" ;;
  "projects describe "*"value(projectNumber)"*) echo "123456789012" ;;
  "billing projects describe"*) echo "${BILLING:-True}" ;;
  "run services describe"*) echo "https://google-ads-mcp-123456789012.us-central1.run.app" ;;
  *" describe "*|*"images describe"*) exit 1 ;;  # nothing exists yet
esac
exit 0
"""
GIT = r"""#!/bin/bash
printf 'git %s\n' "$*" >> "$LOG"
dest="${@: -1}"
mkdir -p "$dest"
printf 'FROM python:3.11-slim\nRUN uv pip install --system .\nCMD ["google-ads-mcp"]\n' > "$dest/Dockerfile"
cp "$dest/Dockerfile" "$CAPTURE/Dockerfile.original"
"""
CURL = "#!/bin/bash\necho 200\n"


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
class DeployScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.bin, self.capture = base / "bin", base / "capture"
        self.bin.mkdir()
        self.capture.mkdir()
        for name, body in (("gcloud", GCLOUD), ("git", GIT), ("curl", CURL)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.log = base / "gcloud.log"
        self.stdin_log = base / "stdin.log"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, answers, *args, billing="True"):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "LOG": str(self.log),
               "STDIN_LOG": str(self.stdin_log), "CAPTURE": str(self.capture), "BILLING": billing}
        r = subprocess.run(["bash", str(SCRIPT), "--project-id", "shaped-buttress-512811-c9", *args],
                           input="\n".join(answers) + "\n", capture_output=True, text=True, env=env, timeout=60)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return r, calls

    # answers: enable APIs, client ID, create repo, build, create Firestore, create SA, secret, deploy
    FULL = ["y", CLIENT_ID, "y", "y", "y", "y", SECRET, "y"]

    def test_full_deploy_sends_expected_commands_and_never_leaks_the_secret(self):
        r, calls = self.run_script(self.FULL)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        joined = "\n".join(calls)
        self.assertIn("services enable run.googleapis.com", joined)
        self.assertIn("googleads.googleapis.com", joined)
        self.assertIn("artifacts repositories create mcp-servers", joined)
        self.assertIn("git clone --quiet --depth 1 --branch v0.0.5 https://github.com/googleads/google-ads-mcp", joined)
        self.assertIn("builds submit", joined)
        self.assertIn("--tag us-central1-docker.pkg.dev/shaped-buttress-512811-c9/mcp-servers/google-ads-mcp:0.0.5", joined)
        self.assertIn("firestore databases create --database=(default) --location=nam5", joined)
        self.assertIn("roles/datastore.user", joined)
        deploy = next(c for c in calls if c.startswith("run deploy"))
        self.assertIn("--allow-unauthenticated", deploy)
        self.assertIn(f"GOOGLE_ADS_MCP_OAUTH_CLIENT_ID={CLIENT_ID}", deploy)
        self.assertIn("GOOGLE_ADS_MCP_BASE_URL=https://google-ads-mcp-123456789012.us-central1.run.app", deploy)
        self.assertIn("GOOGLE_ADS_MCP_STORAGE_TYPE=firestore", deploy)
        self.assertIn("GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET=google-ads-mcp-client-secret:latest", deploy)
        self.assertIn("GOOGLE_ADS_MCP_JWT_SIGNING_KEY=google-ads-mcp-jwt-key:latest", deploy)
        # the secret travels only on stdin to Secret Manager
        self.assertNotIn(SECRET, joined)
        self.assertNotIn(SECRET, out)
        self.assertIn(f"STDIN={SECRET}", self.stdin_log.read_text())
        self.assertIn("https://google-ads-mcp-123456789012.us-central1.run.app/auth/callback", out)
        self.assertIn("https://claude.ai/api/mcp/auth_callback", out)
        self.assertIn("/mcp", out.split("Connector address:")[1])
        self.assertIn("server answers", out)

    def test_firestore_extra_is_added_to_the_submitted_build(self):
        self.run_script(self.FULL)
        self.assertIn("RUN uv pip install --system .\n", (self.capture / "Dockerfile.original").read_text())
        submitted = (self.capture / "Dockerfile.submitted").read_text()
        self.assertIn('RUN uv pip install --system ".[firestore]"', submitted)
        self.assertNotIn("RUN uv pip install --system .\n", submitted)

    def test_billing_off_stops_before_any_change(self):
        r, calls = self.run_script(self.FULL, billing="False")
        self.assertEqual(r.returncode, 2)
        self.assertIn("billing is not enabled", r.stderr)
        self.assertFalse([c for c in calls if c.startswith(("services enable", "run deploy", "builds"))])

    def test_bad_client_id_stops_before_build(self):
        r, calls = self.run_script(["y", "nope", "still-nope", "123"])
        self.assertEqual(r.returncode, 2)
        self.assertFalse([c for c in calls if "builds submit" in c or c.startswith("run deploy")])

    def test_declining_deploy_deploys_nothing(self):
        r, calls = self.run_script(self.FULL[:-1] + ["n"])
        self.assertEqual(r.returncode, 2)
        self.assertFalse([c for c in calls if c.startswith("run deploy")])

    def test_dry_run_changes_nothing(self):
        r, calls = self.run_script(self.FULL, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mutating = ("services enable", "artifacts repositories create", "builds submit", "firestore databases create",
                    "iam service-accounts create", "projects add-iam-policy-binding", "secrets create",
                    "secrets versions", "secrets add-iam-policy-binding", "run deploy")
        self.assertFalse([c for c in calls if c.startswith(mutating)])
        self.assertIn("[dry-run] gcloud run deploy", r.stdout)
        self.assertNotIn(SECRET, r.stdout + r.stderr)

    def test_requires_project_id(self):
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"})
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
