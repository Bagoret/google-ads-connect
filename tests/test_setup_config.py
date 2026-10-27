import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_wheel  # noqa: E402
from gads import macver_shim  # noqa: E402
from setup_config import (NeedsReplace, SetupError, build_server_venv, check_client_file, find_pip_wheel,  # noqa: E402
                          main, normalise_customer_id, pick_server_python, probe_python, server_entry, venv_status,
                          write_desktop, write_mcp_json)

IN_RANGE = (3, 10) <= sys.version_info[:2] <= (3, 13)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.creds = self.base / "home" / ".config" / "gcloud" / "application_default_credentials.json"
        self.creds.parent.mkdir(parents=True)
        self.creds.write_text(json.dumps({"type": "authorized_user", "refresh_token": "SYNTH"}))
        self.server = self.base / "venv" / "bin" / "google-ads-mcp"
        self.server.parent.mkdir(parents=True)
        self.server.write_text("#!/bin/sh\n")
        self.server.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, **over):
        args = {"server": str(self.server), "credentials": str(self.creds), "project_id": "shaped-buttress-512811-c9"}
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
    def test_entry_runs_the_venv_executable_directly(self):
        e = self.entry()
        self.assertEqual(e["command"], str(self.server))
        self.assertEqual(e["args"], [])
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
            self.entry(server="google-ads-mcp")  # must be an absolute path
        with self.assertRaises(SetupError):
            self.entry(server=str(self.base / "venv" / "bin" / "missing"))

    def test_credentials_inside_repo_rejected(self):
        inside = self.repo / "creds.json"
        inside.write_text("{}")
        with self.assertRaises(SetupError):
            server_entry(server=str(self.server), credentials=str(inside), project_id="my-project-1", repo=self.repo)


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
        with self.assertRaises(NeedsReplace):
            write_mcp_json(self.repo, self.entry())
        self.assertEqual(target.read_text(), '{"old": true}')
        write_mcp_json(self.repo, self.entry(), replace=True)
        backups = list(self.repo.glob(".mcp.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '{"old": true}')
        self.assertIn("mcpServers", target.read_text())

    def test_rewriting_the_same_config_is_a_no_op(self):
        write_mcp_json(self.repo, self.entry())
        write_mcp_json(self.repo, self.entry())  # no --replace needed, no backup made
        self.assertEqual(list(self.repo.glob(".mcp.json.bak-*")), [])

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
        self.assertEqual(json.loads(self.cfg().read_text())["mcpServers"]["google-ads-mcp"]["command"], str(self.server))

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
        common = ["--server", str(self.server), "--credentials", str(self.creds), "--project-id", "my-project-1"]
        self.assertEqual(main(["mcp-json", "--repo", str(self.repo), *common]), 0)
        self.assertTrue((self.repo / ".mcp.json").exists())
        self.assertEqual(main(["mcp-json", "--repo", str(self.repo), *common]), 0)  # identical: nothing to do
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["mcp-json", "--repo", str(self.repo), *common[:-1], "other-project-1"])
        self.assertEqual(code, 3)  # needs --replace
        self.assertNotIn("STOP", err.getvalue())  # a question follows in setup_mac.sh, not a stop
        self.assertEqual(main(["customer-id", "123-456-7890"]), 0)
        self.assertEqual(main(["customer-id", "12"]), 2)
        self.assertEqual(main(["project-id", "shaped-buttress-512811-c9"]), 0)
        self.assertEqual(main(["project-id", "YOUR_PROJECT_ID"]), 2)


def fake_python(directory: Path, name: str, version, platform="darwin", mac_ver="26.2", expat_error="") -> str:
    """A stand-in interpreter that answers setup_config's probe like a real one would."""
    path = Path(directory) / name
    info = json.dumps({"version": list(version), "platform": platform, "mac_ver": mac_ver, "expat_error": expat_error})
    path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{info}\nEOF\n")
    path.chmod(0o755)
    return str(path)


BROKEN = "ImportError: dlopen(pyexpat.cpython-312-darwin.so): Symbol not found: _XML_SetAllocTrackerActivationThreshold"


class ServerPythonTest(Fixture):
    def test_probe_flags_the_macos_26_pyexpat_breakage(self):
        info = probe_python(fake_python(self.base, "py312", (3, 12, 16), mac_ver="", expat_error=BROKEN))
        self.assertTrue(info["in_range"])
        self.assertTrue(info["needs_shim"])
        self.assertIn("pyexpat", info["problem"])

    def test_probe_of_a_healthy_python(self):
        info = probe_python(fake_python(self.base, "py313", (3, 13, 9)))
        self.assertTrue(info["in_range"])
        self.assertFalse(info["needs_shim"])

    def test_probe_of_the_real_interpreter(self):
        info = probe_python(sys.executable)
        self.assertEqual(info["version"], tuple(sys.version_info[:3]))
        self.assertFalse(info["needs_shim"])  # Linux/CI: mac_ver() is meant to be empty there

    def test_unrunnable_candidate_is_skipped(self):
        bad = self.base / "nope"
        bad.write_text("#!/bin/sh\nexit 1\n")
        bad.chmod(0o755)
        good = fake_python(self.base, "py312", (3, 12, 16))
        self.assertEqual(pick_server_python([str(bad), str(self.base / "missing"), good])["path"], good)

    def test_prefers_a_healthy_python_then_the_newest(self):
        broken = fake_python(self.base, "py313", (3, 13, 9), mac_ver="", expat_error=BROKEN)
        healthy = fake_python(self.base, "py311", (3, 11, 9))
        newer = fake_python(self.base, "py312", (3, 12, 16))
        self.assertEqual(pick_server_python([broken, healthy, newer])["path"], newer)
        self.assertEqual(pick_server_python([broken])["path"], broken)  # usable, with the shim

    def test_versions_outside_3_10_to_3_13_rejected(self):
        old = fake_python(self.base, "py39", (3, 9, 6))
        new = fake_python(self.base, "py315", (3, 15, 1), mac_ver="", expat_error=BROKEN)
        with self.assertRaises(SetupError) as ctx:
            pick_server_python([old, new])
        self.assertIn("3.10", str(ctx.exception))

    def test_cli_prints_the_chosen_path(self):
        good = fake_python(self.base, "py312", (3, 12, 16), mac_ver="", expat_error=BROKEN)
        self.assertEqual(main(["server-python", good]), 0)
        self.assertEqual(main(["server-python", str(self.base / "missing")]), 2)


class MacVerShimTest(unittest.TestCase):
    PLIST = ('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">\n<dict>\n'
             '\t<key>ProductBuildVersion</key>\n\t<string>25C56</string>\n'
             '\t<key>ProductVersion</key>\n\t<string>26.2</string>\n</dict>\n</plist>\n')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plist = Path(self.tmp.name) / "SystemVersion.plist"
        self.plist.write_text(self.PLIST)

    def tearDown(self):
        self.tmp.cleanup()

    def broken_platform(self):
        return types.SimpleNamespace(mac_ver=lambda release="", versioninfo=("", "", ""), machine="":
                                     (release, versioninfo, machine))

    def test_reads_the_version_without_an_xml_parser(self):
        self.assertEqual(macver_shim.product_version(str(self.plist)), "26.2")

    def test_restores_mac_ver_when_it_is_empty_on_macos(self):
        plat = self.broken_platform()
        self.assertTrue(macver_shim.install(plat, "darwin", str(self.plist)))
        release, versioninfo, machine = plat.mac_ver()
        self.assertEqual(release, "26.2")
        self.assertEqual(tuple(map(int, release.split("."))), (26, 2))  # what truststore and packaging do
        self.assertTrue(machine)

    def test_leaves_a_working_mac_ver_alone(self):
        plat = types.SimpleNamespace(mac_ver=lambda: ("26.3", ("", "", ""), "arm64"))
        original = plat.mac_ver
        self.assertFalse(macver_shim.install(plat, "darwin", str(self.plist)))
        self.assertIs(plat.mac_ver, original)

    def test_does_nothing_off_macos_or_without_a_version(self):
        plat = self.broken_platform()
        self.assertFalse(macver_shim.install(plat, "linux", str(self.plist)))
        self.plist.write_text("<plist></plist>")
        self.assertFalse(macver_shim.install(plat, "darwin", str(self.plist), sw_vers="/nonexistent/sw_vers"))
        self.assertEqual(plat.mac_ver()[0], "")

    def test_importing_the_shim_never_breaks_startup(self):
        r = subprocess.run([sys.executable, "-I", "-c", "import runpy; runpy.run_path(%r)" % macver_shim.__file__],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(IN_RANGE, "needs a Python 3.10-3.13 test interpreter")
@unittest.skipIf(find_pip_wheel(sys.executable) is None and subprocess.run(
    [sys.executable, "-m", "pip", "--version"], capture_output=True).returncode != 0, "no pip available offline")
class ServerVenvTest(Fixture):
    """Creates a real venv and installs a synthetic google-ads-mcp wheel from a local folder (no network)."""

    def setUp(self):
        super().setUp()
        self.wheels = self.base / "wheels"
        fake_wheel.build(self.wheels)
        self.venv = self.base / "share" / "mcp-venv"
        self.env = {"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(self.wheels)}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def test_builds_venv_without_ensurepip_and_with_the_shim(self):
        self.assertIsNotNone(venv_status(self.venv))
        exe = build_server_venv(sys.executable, self.venv, log=lambda *_: None)
        self.assertEqual(exe, self.venv / "bin" / "google-ads-mcp")
        self.assertTrue(os.access(exe, os.X_OK))
        self.assertIsNone(venv_status(self.venv))
        py = self.venv / "bin" / "python"
        r = subprocess.run([str(py), "-c", "import sys; print('google_ads_os_macver' in sys.modules)"],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "True", r.stderr)  # the .pth loads the shim at every start
        self.assertNotEqual(subprocess.run([str(py), "-m", "pip", "--version"], capture_output=True).returncode, 0)

    def test_rerun_keeps_a_good_venv_and_rebuilds_a_broken_one(self):
        build_server_venv(sys.executable, self.venv, log=lambda *_: None)
        marker = self.venv / "marker"
        marker.write_text("x")
        build_server_venv(sys.executable, self.venv, log=lambda *_: None)
        self.assertTrue(marker.exists())  # untouched: already up to date
        (self.venv / "bin" / "google-ads-mcp").unlink()
        self.assertIn("google-ads-mcp", venv_status(self.venv))
        build_server_venv(sys.executable, self.venv, log=lambda *_: None)
        self.assertIsNone(venv_status(self.venv))
        self.assertFalse(marker.exists())

    def test_refuses_to_replace_a_folder_that_is_not_a_venv(self):
        self.venv.mkdir(parents=True)
        (self.venv / "important.txt").write_text("keep me")
        with self.assertRaises(SetupError):
            build_server_venv(sys.executable, self.venv, log=lambda *_: None)
        self.assertTrue((self.venv / "important.txt").exists())

    def test_cli_status_and_build(self):
        self.assertEqual(main(["server-venv", "--python", sys.executable, "--venv", str(self.venv), "--status"]), 1)
        self.assertEqual(main(["server-venv", "--python", sys.executable, "--venv", str(self.venv)]), 0)
        self.assertEqual(main(["server-venv", "--python", sys.executable, "--venv", str(self.venv), "--status"]), 0)


if __name__ == "__main__":
    unittest.main()
