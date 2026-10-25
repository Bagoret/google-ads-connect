import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from first_run import hook_message, load_profile, save_profile, status  # noqa: E402
from init_workspace import init_workspace  # noqa: E402

BUSINESS_SPECIFIC = ("K-beauty", "expected: France", "French-market")


def fresh_root() -> tempfile.TemporaryDirectory:
    """A temp copy of the repo skeleton: templates only, no context/ or local/ yet."""
    tmp = tempfile.TemporaryDirectory()
    shutil.copytree(ROOT / "templates", Path(tmp.name) / "templates")
    (Path(tmp.name) / "config").mkdir()
    return tmp


class TemplatesTest(unittest.TestCase):
    def test_templates_exist_and_are_generic(self):
        files = list((ROOT / "templates").rglob("*.*"))
        names = {f.name for f in files}
        for expected in ("business.md", "account-map.md", "measurement.md", "commercial-calendar.md",
                         "brand_lists.json", "campaign_classification.json"):
            self.assertIn(expected, names)
        for f in files:
            text = f.read_text()
            for phrase in BUSINESS_SPECIFIC:
                self.assertNotIn(phrase, text, (f.name, phrase))

    def test_project_instructions_are_generic(self):
        for path in ("CLAUDE.md", "README.md", ".claude/skills/weekly-review/SKILL.md"):
            text = (ROOT / path).read_text()
            for phrase in BUSINESS_SPECIFIC:
                self.assertNotIn(phrase, text, (path, phrase))


class InitWorkspaceTest(unittest.TestCase):
    def test_creates_missing_then_keeps_existing(self):
        with fresh_root() as tmp:
            root = Path(tmp)
            first = init_workspace(root)
            self.assertIn("context/business.md", first["created"])
            self.assertIn("config/brand_lists.json", first["created"])
            (root / "context" / "business.md").write_text("FILLED BY USER")
            second = init_workspace(root)
            self.assertIn("context/business.md", second["kept"])
            self.assertEqual((root / "context" / "business.md").read_text(), "FILLED BY USER")

    def test_reset_requires_confirmation(self):
        with fresh_root() as tmp:
            root = Path(tmp)
            init_workspace(root)
            (root / "context" / "business.md").write_text("FILLED BY USER")
            with self.assertRaises(ValueError):
                init_workspace(root, reset=True)
            self.assertEqual((root / "context" / "business.md").read_text(), "FILLED BY USER")
            result = init_workspace(root, reset=True, confirm=True)
            self.assertIn("context/business.md", result["reset"])
            self.assertIn("UNKNOWN", (root / "context" / "business.md").read_text())


class ProfileTest(unittest.TestCase):
    def test_invalid_values_rejected(self):
        with fresh_root() as tmp:
            for bad in ({"relationship": "boss"}, {"access": "superuser"}, {"uses": ["hacking"]}):
                args = {"relationship": "agency", "access": "read_only", "uses": ["weekly-review"], **bad}
                with self.assertRaises(ValueError):
                    save_profile(Path(tmp), **args)

    def test_profile_saved_privately_and_minimal(self):
        with fresh_root() as tmp:
            path = save_profile(Path(tmp), relationship="freelancer", access="read_only",
                                uses=["weekly-review", "search-term-review"], display_name="Sam")
            data = load_profile(Path(tmp))
            self.assertEqual(data["relationship"], "freelancer")
            self.assertNotIn("language", data)  # reports and replies are English only
            self.assertEqual(set(data), {"display_name", "relationship", "access", "uses",
                                         "first_run_completed_at"})
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_local_folder_is_gitignored(self):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "local/profile.json"])
        self.assertEqual(r.returncode, 0)


class StatusAndHookTest(unittest.TestCase):
    def test_brand_new_workspace(self):
        with fresh_root() as tmp:
            st = status(Path(tmp))
            self.assertFalse(st["context_initialised"])
            self.assertFalse(st["profile"])
            msg = hook_message(st)
            self.assertIn("init_workspace.py", msg)
            self.assertIn("onboarding", msg)

    def test_new_person_existing_business(self):
        with fresh_root() as tmp:
            init_workspace(Path(tmp))
            st = status(Path(tmp))
            self.assertTrue(st["context_initialised"])
            self.assertGreater(st["business_blockers"], 0)
            msg = hook_message(st)
            self.assertIn("person setup", msg)

    def test_silent_when_everything_is_done(self):
        st = {"context_initialised": True, "profile": True, "business_blockers": 0, "mcp_configured": True}
        self.assertEqual(hook_message(st), "")

    def test_profile_done_but_blockers_remain(self):
        st = {"context_initialised": True, "profile": True, "business_blockers": 3, "mcp_configured": True}
        msg = hook_message(st)
        self.assertIn("3", msg)
        self.assertNotIn("person setup", msg)

    def test_cli_has_no_language_option(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "first_run.py"), "save", "--help"],
                           capture_output=True, text=True)
        self.assertNotIn("--language", r.stdout)

    def test_session_start_hook_configured(self):
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
        commands = [h["command"] for entry in settings["hooks"]["SessionStart"] for h in entry["hooks"]]
        self.assertTrue(any("first_run.py" in c and "--hook" in c for c in commands))


if __name__ == "__main__":
    unittest.main()
