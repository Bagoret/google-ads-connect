#!/usr/bin/env python3
"""Write the MCP configuration files for the Google Ads server (used by scripts/setup_mac.sh).

  python3 scripts/setup_config.py customer-id 123-456-7890           # validate; prints 1234567890
  python3 scripts/setup_config.py project-id my-project-123          # validate a Cloud project ID
  python3 scripts/setup_config.py client-file ~/.config/google-ads-os/client_secret.json   # Desktop client?
  python3 scripts/setup_config.py server-python /opt/homebrew/bin/python3.12 …   # pick a Python for the server
  python3 scripts/setup_config.py server-venv --python /opt/homebrew/bin/python3.12 [--venv DIR] [--status]
  python3 scripts/setup_config.py mcp-json --server ~/.local/share/google-ads-os/mcp-venv/bin/google-ads-mcp \\
      --credentials ~/.config/gcloud/application_default_credentials.json --project-id my-project [--replace]
  python3 scripts/setup_config.py desktop  --server … --credentials … --project-id … [--config PATH] [--replace]

server-venv installs Google's server (pinned) into its own virtual environment, outside the repo. It never
runs ensurepip (which breaks on macOS 26.0-26.2 with Homebrew Python, see docs/mcp-setup.md › Troubleshooting);
it runs the interpreter's bundled pip wheel directly and adds a small mac_ver shim (scripts/gads/connect/macver_shim.py).
Both writers create the file private to your user (mode 600), never add a developer token, and back up any
file they change to <name>.bak-<timestamp> first. Writing an identical entry is a no-op; a different existing
entry is only replaced with --replace.
Exit code: 0 = done, 1 = (--status) not installed yet, 2 = stopped (reason on stderr), 3 = needs --replace.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.core.files import write_private_json  # noqa: E402
from gads.core.ids import parse_customer_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "google-ads-mcp"
SERVER_VERSION = "0.0.5"  # the version this repo's contract tests were built against
SERVER_SPEC = f"{SERVER_NAME}=={SERVER_VERSION}"
SERVER_PYTHONS = ((3, 10), (3, 13))  # inclusive; google-ads-mcp needs >=3.10, newer ones may lack grpcio wheels
DEFAULT_VENV = Path.home() / ".local" / "share" / "google-ads-os" / "mcp-venv"
SHIM_SOURCE = Path(__file__).resolve().parent / "gads" / "connect" / "macver_shim.py"
SHIM_MODULE = "google_ads_os_macver"
PROBE = r"""
import json, platform, sys
try:
    import pyexpat
    problem = ""
except Exception as exc:
    problem = ("%s: %s" % (type(exc).__name__, exc))[:300]
print(json.dumps({"version": list(sys.version_info[:3]), "platform": sys.platform,
                  "mac_ver": platform.mac_ver()[0], "expat_error": problem}))
"""
PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DESKTOP_CONFIG = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


class SetupError(Exception):
    pass


class NeedsReplace(SetupError):
    """The file already has a different entry; the caller may ask the user and retry with --replace."""


def normalise_customer_id(text: str) -> str:
    digits = parse_customer_id(text)
    if not digits:
        raise SetupError(f"not a 10-digit Google Ads customer ID: {text!r}")
    return digits


def check_project_id(project_id: str) -> str:
    if not PROJECT_ID.match(project_id or ""):
        raise SetupError(f"not a Google Cloud project ID: {project_id!r} (lowercase letters, digits, hyphens)")
    return project_id


def check_client_file(path: Path) -> None:
    """The OAuth client JSON must be a Desktop app client ("installed"); its contents are never printed."""
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError(f"{path} is not a readable OAuth client JSON file")
    if isinstance(data, dict) and "web" in data:
        raise SetupError("this is a 'Web application' client; create a 'Desktop app' client and download its JSON")
    if not (isinstance(data, dict) and isinstance(data.get("installed"), dict)
            and data["installed"].get("client_id")):
        raise SetupError(f"{path} does not look like a Desktop app OAuth client JSON file")


def server_entry(server: str, credentials: str, project_id: str, login_customer_id: str | None = None,
                 repo: Path = ROOT) -> dict:
    server_path = Path(server).expanduser()
    if not server_path.is_absolute() or not server_path.is_file() or not os.access(server_path, os.X_OK):
        raise SetupError(f"the server must be an existing absolute path to an executable (got {server!r}); "
                         "install it with `setup_config.py server-venv`")
    creds = Path(credentials).expanduser()
    if not creds.is_file():
        raise SetupError(f"credentials file not found: {creds}")
    try:
        creds.resolve().relative_to(Path(repo).resolve())
        raise SetupError("credentials file is inside the repo folder; keep it outside (e.g. ~/.config/)")
    except ValueError:
        pass
    check_project_id(project_id)
    env = {"GOOGLE_APPLICATION_CREDENTIALS": str(creds), "GOOGLE_PROJECT_ID": project_id}
    if login_customer_id:
        env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] = normalise_customer_id(login_customer_id)
    return {"command": str(server_path), "args": [], "env": env}


# --- the server's own Python environment -------------------------------------------------------------

def probe_python(path: str) -> dict | None:
    """Ask an interpreter for its version and whether it can read the macOS version. None if it cannot run."""
    try:
        r = subprocess.run([path, "-I", "-c", PROBE], capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    if not isinstance(data, dict):
        return None
    version = tuple(int(x) for x in data.get("version", [])[:3])
    darwin = data.get("platform") == "darwin"
    problem = ""
    if darwin and data.get("expat_error"):
        problem = f"cannot load pyexpat ({data['expat_error']}), so platform.mac_ver() is empty"
    elif darwin and not data.get("mac_ver"):
        problem = "platform.mac_ver() is empty"
    return {"path": path, "version": version, "in_range": SERVER_PYTHONS[0] <= version[:2] <= SERVER_PYTHONS[1],
            "needs_shim": bool(problem), "problem": problem}


def pick_server_python(candidates: list[str]) -> dict:
    """The best interpreter for the server: in range, healthy before broken, then newest."""
    seen, usable, rejected = set(), [], []
    for cand in candidates:
        real = os.path.realpath(cand)
        if real in seen or not os.path.isfile(real):
            continue
        seen.add(real)
        info = probe_python(cand)
        if info and info["in_range"]:
            usable.append(info)
        elif info:
            rejected.append(f"{cand} is Python {'.'.join(map(str, info['version']))}")
    if not usable:
        low, high = (".".join(map(str, v)) for v in SERVER_PYTHONS)
        found = f" (found: {'; '.join(rejected)})" if rejected else ""
        raise SetupError(f"no Python {low}-{high} found for Google's server{found}")
    usable.sort(key=lambda i: (i["needs_shim"], tuple(-x for x in i["version"])))
    return usable[0]


def _venv_python(venv: Path) -> Path:
    return Path(venv) / "bin" / "python"


def venv_status(venv: Path) -> str | None:
    """None if the venv has the pinned server, the shim and a working Python; else what is wrong."""
    venv = Path(venv)
    if not (venv / "pyvenv.cfg").is_file():
        return f"no server environment at {venv}"
    exe = venv / "bin" / SERVER_NAME
    if not (exe.is_file() and os.access(exe, os.X_OK)):
        return f"{exe} (the google-ads-mcp command) is missing"
    check = ("import importlib.metadata as m, importlib.util as u, sys; "
             f"print(m.version({SERVER_NAME!r}) if u.find_spec({SHIM_MODULE!r}) else 'no-shim')")
    try:
        r = subprocess.run([str(_venv_python(venv)), "-c", check], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"its Python does not run ({type(exc).__name__}); the Python it was made from may have been removed"
    found = r.stdout.strip()
    if r.returncode != 0:
        return "its Python does not run or google-ads-mcp is not installed"
    if found == "no-shim":
        return "it was made by an older setup (no mac_ver shim)"
    if found != SERVER_VERSION:
        return f"it has google-ads-mcp {found}, not the pinned {SERVER_VERSION}"
    return None


def find_pip_wheel(python: str) -> Path | None:
    """The pip wheel bundled with an interpreter's ensurepip (or its WHEEL_PKG_DIR), newest first."""
    code = ("import ensurepip, os, sysconfig; d = os.path.join(os.path.dirname(ensurepip.__file__), '_bundled'); "
            "print(d); print(sysconfig.get_config_var('WHEEL_PKG_DIR') or '')")
    try:
        r = subprocess.run([python, "-I", "-c", code], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    wheels = [w for d in r.stdout.splitlines() if d.strip() for w in Path(d.strip()).glob("pip-*.whl")]

    def version(w: Path) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", w.name.split("-")[1])[:3])
    return max(wheels, key=version) if wheels else None


def _say(message: str) -> None:
    print(message, flush=True)  # flush so it appears before pip's own output


def build_server_venv(python: str, venv: Path, log=_say) -> Path:
    """Create (or repair) the server venv and install the pinned server. Returns the server executable."""
    venv = Path(venv).expanduser()
    exe = venv / "bin" / SERVER_NAME
    if venv_status(venv) is None:
        log(f"Google's server {SERVER_VERSION} is already installed in {venv}; nothing to do.")
        return exe
    info = probe_python(python)
    if not info or not info["in_range"]:
        raise SetupError(f"{python} is not a usable Python 3.10-3.13")
    if venv.exists():
        if not (venv / "pyvenv.cfg").is_file():
            raise SetupError(f"{venv} exists but is not a Python environment; move it away, then re-run")
        log(f"Rebuilding {venv} ({venv_status(venv)}).")
        shutil.rmtree(venv)
    if info["needs_shim"]:
        log(f"Note: {python}: {info['problem']}. Using a workaround inside the server's own environment "
            "(see docs/mcp-setup.md › Troubleshooting).")
    venv.parent.mkdir(parents=True, exist_ok=True)
    # --without-pip: venv's ensurepip step runs pip, whose truststore import crashes when mac_ver() is empty,
    # and ensurepip deliberately drops PIP_* environment variables, so no setting can avoid that crash.
    _run([python, "-m", "venv", "--without-pip", str(venv)], "create the server environment")
    vpy = str(_venv_python(venv))
    site = subprocess.run([vpy, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                          capture_output=True, text=True, timeout=60).stdout.strip()
    if not site:
        raise SetupError(f"could not find the site-packages folder of {venv}")
    shutil.copyfile(SHIM_SOURCE, Path(site) / f"{SHIM_MODULE}.py")
    (Path(site) / f"{SHIM_MODULE}.pth").write_text(f"import {SHIM_MODULE}\n", encoding="utf-8")
    quiet = ["--disable-pip-version-check", "--no-input", "--prefer-binary"]
    wheel = find_pip_wheel(python)
    if wheel:  # run the bundled pip straight from its wheel, with the venv's (shimmed) Python
        cmd = [vpy, str(wheel / "pip"), "install", *quiet, SERVER_SPEC]
    elif subprocess.run([python, "-m", "pip", "--version"], capture_output=True).returncode == 0:
        cmd = [python, "-m", "pip", "--python", vpy, "install", *quiet, SERVER_SPEC]
    else:
        raise SetupError(f"{python} has no bundled pip to install with; install python@3.12 with Homebrew")
    log(f"Installing {SERVER_SPEC} into {venv} (downloads from PyPI, about a minute)...")
    _run(cmd, f"install {SERVER_SPEC}")
    problem = venv_status(venv)
    if problem:
        raise SetupError(f"the server environment is still not usable: {problem}")
    return exe


def _run(cmd: list[str], what: str) -> None:
    try:
        r = subprocess.run(cmd, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError(f"could not {what}: {type(exc).__name__}")
    if r.returncode != 0:
        raise SetupError(f"could not {what} (exit {r.returncode}; see the messages above)")


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.bak-{stamp}-{n}")
    shutil.copy2(path, target)
    os.chmod(target, 0o600)
    return target


def write_mcp_json(repo: Path, entry: dict, replace: bool = False) -> Path:
    path = Path(repo) / ".mcp.json"
    wanted = {"mcpServers": {SERVER_NAME: entry}}
    if path.exists():
        try:
            if json.loads(path.read_text(encoding="utf-8")) == wanted:
                return path
        except ValueError:
            pass
        if not replace:
            raise NeedsReplace(f"{path} already exists; re-run with --replace to back it up and rewrite it")
        _backup(path)
    write_private_json(path, wanted)
    return path


def write_desktop(config: Path, entry: dict, replace: bool = False) -> bool:
    """Add the server to Claude Desktop's config, keeping everything else. Returns False if already identical."""
    config = Path(config)
    data: dict = {}
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8") or "{}")
        except ValueError:
            raise SetupError(f"{config} is not valid JSON; fix or move it, then re-run (it was not changed)")
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise SetupError(f"{config} has an unexpected layout; it was not changed")
    servers = data.setdefault("mcpServers", {})
    if servers.get(SERVER_NAME) == entry:
        return False
    if SERVER_NAME in servers and not replace:
        raise NeedsReplace(f"{config} already has a different '{SERVER_NAME}' entry; re-run with --replace")
    if config.exists():
        _backup(config)
    servers[SERVER_NAME] = entry
    write_private_json(config, data)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cid = sub.add_parser("customer-id", help="validate a customer ID and print it as 10 digits")
    cid.add_argument("value")
    sub.add_parser("project-id", help="validate a Google Cloud project ID").add_argument("value")
    sub.add_parser("client-file", help="check the OAuth client JSON is a Desktop app client").add_argument("value")
    sub.add_parser("server-python", help="pick a Python 3.10-3.13 for the server; prints its path").add_argument(
        "candidates", nargs="+")
    sv = sub.add_parser("server-venv", help="install the pinned server into its own virtual environment")
    sv.add_argument("--python", required=True)
    sv.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    sv.add_argument("--status", action="store_true", help="only report whether it is installed (exit 0/1)")
    for name in ("mcp-json", "desktop"):
        p = sub.add_parser(name)
        p.add_argument("--server", required=True, help="absolute path of the google-ads-mcp executable")
        p.add_argument("--credentials", required=True)
        p.add_argument("--project-id", required=True)
        p.add_argument("--login-customer-id")
        p.add_argument("--replace", action="store_true")
        if name == "mcp-json":
            p.add_argument("--repo", type=Path, default=ROOT)
        else:
            p.add_argument("--config", type=Path, default=DESKTOP_CONFIG)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "customer-id":
            print(normalise_customer_id(args.value))
            return 0
        if args.cmd == "project-id":
            check_project_id(args.value)
            return 0
        if args.cmd == "client-file":
            check_client_file(Path(args.value))
            return 0
        if args.cmd == "server-python":
            info = pick_server_python(args.candidates)
            if info["needs_shim"]:
                print(f"Note: {info['path']}: {info['problem']}; setup will work around it.", file=sys.stderr)
            print(info["path"])
            return 0
        if args.cmd == "server-venv":
            if args.status:
                problem = venv_status(args.venv)
                print(problem or f"Google's server {SERVER_VERSION} is installed in {args.venv}")
                return 1 if problem else 0
            print(f"Server command: {build_server_venv(args.python, args.venv)}")
            return 0
        repo = getattr(args, "repo", ROOT)
        entry = server_entry(args.server, args.credentials, args.project_id, args.login_customer_id, repo=repo)
        if args.cmd == "mcp-json":
            print(f"Wrote {write_mcp_json(repo, entry, args.replace)} (unchanged if it already matched)")
        else:
            existed = args.config.exists()
            if not write_desktop(args.config, entry, args.replace):
                print(f"{args.config} already has this exact '{SERVER_NAME}' entry; nothing changed.")
                return 0
            note = " (previous version backed up next to it)" if existed else ""
            print(f"Added '{SERVER_NAME}' to {args.config}{note}. Restart Claude Desktop.")
        return 0
    except NeedsReplace as exc:  # not an error: callers (setup_mac.sh) ask before passing --replace
        print(f"Note: {exc}", file=sys.stderr)
        return 3
    except SetupError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
