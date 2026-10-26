#!/usr/bin/env python3
"""Write the MCP configuration files for the Google Ads server (used by scripts/setup_mac.sh).

  python3 scripts/setup_config.py customer-id 123-456-7890           # validate; prints 1234567890
  python3 scripts/setup_config.py project-id my-project-123          # validate a Cloud project ID
  python3 scripts/setup_config.py client-file ~/.config/google-ads-os/client_secret.json   # Desktop client?
  python3 scripts/setup_config.py mcp-json --pipx /opt/homebrew/bin/pipx \\
      --credentials ~/.config/gcloud/application_default_credentials.json --project-id my-project [--replace]
  python3 scripts/setup_config.py desktop  --pipx … --credentials … --project-id … [--config PATH] [--replace]

Both writers create the file private to your user (mode 600), never add a developer token, and back up any
file they change to <name>.bak-<timestamp> first. An existing different server entry is only replaced with
--replace. Exit code: 0 = done, 2 = stopped (reason on stderr).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.files import write_private_json  # noqa: E402
from gads.ids import parse_customer_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "google-ads-mcp"
SERVER_SPEC = "google-ads-mcp==0.0.5"  # the version this repo's contract tests were built against
PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DESKTOP_CONFIG = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


class SetupError(Exception):
    pass


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


def server_entry(pipx: str, credentials: str, project_id: str, login_customer_id: str | None = None,
                 repo: Path = ROOT) -> dict:
    pipx_path = Path(pipx).expanduser()
    if not pipx_path.is_absolute() or not pipx_path.exists():
        raise SetupError(f"pipx must be an existing absolute path (got {pipx!r}); find it with `command -v pipx`")
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
    return {"command": str(pipx_path), "args": ["run", "--spec", SERVER_SPEC, SERVER_NAME], "env": env}


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
    if path.exists():
        if not replace:
            raise SetupError(f"{path} already exists; re-run with --replace to back it up and rewrite it")
        _backup(path)
    write_private_json(path, {"mcpServers": {SERVER_NAME: entry}})
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
        raise SetupError(f"{config} already has a different '{SERVER_NAME}' entry; re-run with --replace")
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
    for name in ("mcp-json", "desktop"):
        p = sub.add_parser(name)
        p.add_argument("--pipx", required=True)
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
        repo = getattr(args, "repo", ROOT)
        entry = server_entry(args.pipx, args.credentials, args.project_id, args.login_customer_id, repo=repo)
        if args.cmd == "mcp-json":
            print(f"Wrote {write_mcp_json(repo, entry, args.replace)}")
        else:
            existed = args.config.exists()
            if not write_desktop(args.config, entry, args.replace):
                print(f"{args.config} already has this exact '{SERVER_NAME}' entry; nothing changed.")
                return 0
            note = " (previous version backed up next to it)" if existed else ""
            print(f"Added '{SERVER_NAME}' to {args.config}{note}. Restart Claude Desktop.")
        return 0
    except SetupError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
