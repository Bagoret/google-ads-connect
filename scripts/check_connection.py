#!/usr/bin/env python3
"""Preflight checker for the Google Ads MCP connection (OAuth / Application Default Credentials).

Run it on the machine where you set up the connection:
  python3 scripts/check_connection.py                       # configuration only, no network
  python3 scripts/check_connection.py --live                # also start the server and check its tools
  python3 scripts/check_connection.py --live --customer-id 123-456-7890   # also check account access

It never prints secrets: token values and credential contents are only checked, never shown.
Exit code: 0 = no failures, 1 = at least one failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gads.logbook import StopAnalysis  # noqa: E402
from gads.mcp_client import McpError, McpStdioClient, extract_payload  # noqa: E402
from gads.ids import parse_customer_id  # noqa: E402
from gads.mcp_config import STRUCTURED_PARAMS, find_search_tool, load_server_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SETUP = "see docs/mcp-setup.md"
CREDENTIAL_TYPES = {"authorized_user", "service_account", "impersonated_service_account", "external_account"}
ACCESSIBLE_TOOL_NAMES = ("customers_list_accessible_customers", "list_accessible_customers")


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | info | skipped
    detail: str
    fix: str = ""


def _default_adc_path() -> Path:
    if os.environ.get("CLOUDSDK_CONFIG"):
        return Path(os.environ["CLOUDSDK_CONFIG"]) / "application_default_credentials.json"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def _check_python() -> Check:
    v = sys.version_info
    if v >= (3, 10):
        return Check("python", "ok", f"Python {v.major}.{v.minor}")
    return Check("python", "fail", f"Python {v.major}.{v.minor}", "install Python 3.10 or newer")


def _check_gitignored(repo: Path) -> Check:
    try:
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".mcp.json"], capture_output=True)
    except FileNotFoundError:
        return Check(".mcp.json ignored by git", "info", "git not installed; could not check")
    if r.returncode == 0:
        return Check(".mcp.json ignored by git", "ok", "will not be committed")
    if r.returncode == 1:
        return Check(".mcp.json ignored by git", "fail", "git would commit .mcp.json",
                     "add .mcp.json to .gitignore before putting any value in it")
    return Check(".mcp.json ignored by git", "info", "not a git repository; could not check")


def _check_credentials(env: dict, repo: Path) -> list[Check]:
    raw = env.get("GOOGLE_APPLICATION_CREDENTIALS")
    path = Path(raw).expanduser() if raw else _default_adc_path()
    source = "GOOGLE_APPLICATION_CREDENTIALS" if raw else "default gcloud location"
    if not path.exists():
        if raw:
            return [Check("credentials file", "fail", f"not found: {path}",
                          "re-run `gcloud auth application-default login …` and copy the printed path")]
        return [Check("credentials file", "warn", f"GOOGLE_APPLICATION_CREDENTIALS not set and no file at {path}",
                      "set GOOGLE_APPLICATION_CREDENTIALS in .mcp.json (option A), unless you use google-ads.yaml (option C)")]
    checks = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [Check("credentials file", "fail", f"{path} is not readable JSON",
                      "re-create it with `gcloud auth application-default login …`")]
    kind = data.get("type") if isinstance(data, dict) else None
    if kind not in CREDENTIAL_TYPES:
        checks.append(Check("credentials file", "fail", f"unrecognised credentials type in {path}",
                            "use the file written by `gcloud auth application-default login`"))
    elif kind == "authorized_user" and not data.get("refresh_token"):
        checks.append(Check("credentials file", "fail", "user credentials have no refresh token",
                            "re-run `gcloud auth application-default login` with the --scopes and --client-id-file flags"))
    else:
        checks.append(Check("credentials file", "ok", f"{kind} credentials ({source}): {path}"))
    if os.name != "nt" and path.stat().st_mode & 0o077:
        checks.append(Check("credentials permissions", "warn", "readable by other users on this machine",
                            f"run: chmod 600 {path}"))
    else:
        checks.append(Check("credentials permissions", "ok", "private to your user"))
    try:
        path.resolve().relative_to(repo.resolve())
        checks.append(Check("credentials location", "warn", "credentials file is inside the repo folder",
                            "move it outside the repo (e.g. ~/.config/google-ads-os/) and update .mcp.json"))
    except ValueError:
        checks.append(Check("credentials location", "ok", "outside the repo"))
    return checks


def _check_env_values(env: dict) -> list[Check]:
    checks = []
    project = env.get("GOOGLE_PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT")
    checks.append(Check("Google Cloud project", "ok", f"project {project}") if project else
                  Check("Google Cloud project", "warn", "GOOGLE_PROJECT_ID not set",
                        "add your Cloud project ID to .mcp.json env"))
    checks.append(Check("developer token", "ok", "set (value hidden)") if env.get("GOOGLE_ADS_DEVELOPER_TOKEN") else
                  Check("developer token", "info", "not set — optional per upstream docs; add one only if the API asks"))
    login = env.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if not login:
        checks.append(Check("login customer ID", "info", "not set (fine unless you access the account via a manager account)"))
    elif parse_customer_id(login):
        checks.append(Check("login customer ID", "ok", f"manager account {parse_customer_id(login)}"))
    else:
        checks.append(Check("login customer ID", "fail", "GOOGLE_ADS_LOGIN_CUSTOMER_ID is not a 10-digit ID",
                            "use the manager account ID (digits only) or delete the line"))
    return checks


def _live_checks(cmd: list[str], env: dict, customer_id: str | None, timeout_s: float) -> list[Check]:
    checks: list[Check] = []
    try:
        with McpStdioClient(cmd, env=env, timeout_s=timeout_s) as client:
            info = client.initialize()
            tools = {t["name"]: t for t in client.list_tools()}
            checks.append(Check("server starts", "ok",
                                f"{info.get('name', '?')} {info.get('version', '')}".strip() + f", {len(tools)} tools"))
            search = find_search_tool(tools)
            props = set((search or {}).get("inputSchema", {}).get("properties", {}))
            if search and STRUCTURED_PARAMS <= props:
                checks.append(Check("search tool contract", "ok", f"{search['name']} accepts {sorted(STRUCTURED_PARAMS)}"))
            else:
                checks.append(Check("search tool contract", "fail",
                                    f"no search tool with {sorted(STRUCTURED_PARAMS)}; server offers {sorted(tools)}",
                                    "pin the server version the scripts were tested with (see docs/mcp-setup.md)"))
            if not customer_id:
                checks.append(Check("customer access", "info", "pass --customer-id to check account access"))
                return checks
            wanted = parse_customer_id(customer_id)
            if not wanted:
                checks.append(Check("customer access", "fail", f"not a 10-digit customer ID: {customer_id}"))
                return checks
            name = next((n for n in ACCESSIBLE_TOOL_NAMES if n in tools), None)
            if not name:
                checks.append(Check("customer access", "fail", "server has no list-accessible-customers tool"))
                return checks
            try:
                _, payload = extract_payload(client.call_tool(name, {}))
            except StopAnalysis as exc:
                checks.append(Check("customer access", "fail", exc.reason[:300],
                                    "check the Google account you signed in with has access to this Ads account"))
                return checks
            ids = payload.get("result", payload) if isinstance(payload, dict) else payload
            found = {re.sub(r"\D", "", str(i)) for i in (ids or [])}
            if wanted in found:
                checks.append(Check("customer access", "ok", f"{wanted} is accessible ({len(found)} account(s) visible)"))
            else:
                checks.append(Check("customer access", "fail", f"{wanted} is not among the {len(found)} accessible account(s)",
                                    "ask an admin to add your Google login to the account, or set GOOGLE_ADS_LOGIN_CUSTOMER_ID "
                                    "if access is via a manager account"))
    except (McpError, OSError) as exc:
        failed = "server starts" if not checks else "customer access"
        checks.append(Check(failed, "fail", f"MCP server error: {exc}",
                            "run the server command from .mcp.json in a terminal to see its own error output"))
    return checks


RESETUP = "re-run `bash scripts/setup_mac.sh` (it installs the server in its own folder), or see docs/mcp-setup.md"


def _check_launcher(cmd: list[str]) -> Check:
    if not shutil.which(cmd[0]):
        return Check("server launcher", "fail", f"`{cmd[0]}` is not installed or not on PATH", RESETUP)
    if Path(cmd[0]).name == "pipx" and "run" in cmd[1:]:
        return Check("server launcher", "warn", "older `pipx run` setup: it re-downloads the server and fails on "
                     "macOS 26.0-26.2 with Homebrew Python (docs/mcp-setup.md › Troubleshooting)", RESETUP)
    return Check("server launcher", "ok", f"`{cmd[0]}` found")


def run_checks(repo: Path, live: bool = False, customer_id: str | None = None, timeout_s: float = 180) -> list[Check]:
    checks = [_check_python()]
    cfg_path = repo / ".mcp.json"
    if not cfg_path.exists():
        checks.append(Check(".mcp.json", "fail", "not found", f"copy .mcp.json.example to .mcp.json and fill it in ({SETUP})"))
        cmd, env = None, None
    else:
        try:
            cmd, env = load_server_config(cfg_path)
            checks.append(Check(".mcp.json", "ok", "parsed; no placeholders; ${VAR} references resolved"))
        except (StopAnalysis, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, StopAnalysis) else f"invalid structure ({type(exc).__name__})"
            checks.append(Check(".mcp.json", "fail", reason, SETUP))
            cmd, env = None, None
    checks.append(_check_gitignored(repo))
    if cmd is None:
        checks += [Check(n, "skipped", "needs a valid .mcp.json") for n in ("server launcher", "credentials file")]
    else:
        checks.append(_check_launcher(cmd))
        checks += _check_credentials(env, repo)
        checks += _check_env_values(env)
    if live:
        if any(c.status == "fail" for c in checks):
            checks += [Check(n, "skipped", "fix the failures above first")
                       for n in ("server starts", "search tool contract", "customer access")]
        else:
            checks += _live_checks(cmd, env, customer_id, timeout_s)
    return checks


LABEL = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "info": "INFO", "skipped": "SKIP"}


def render(checks: list[Check]) -> str:
    lines = ["Google Ads MCP connection check", ""]
    for c in checks:
        lines.append(f"[{LABEL[c.status]}] {c.name}: {c.detail}")
        if c.fix and c.status in ("warn", "fail"):
            lines.append(f"       → {c.fix}")
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    lines += ["", f"{len(fails)} failure(s), {len(warns)} warning(s)."]
    if fails:
        lines.append(f"Next step: {fails[0].fix or fails[0].detail}")
    elif not any(c.name == "customer access" and c.status == "ok" for c in checks):
        lines.append("Next step: run again with --live --customer-id <your account ID>.")
    else:
        lines.append("Next step: python3 scripts/snapshot.py --query customer_settings --customer-id <ID>, "
                     "then scripts/inspect_snapshot.py on the file it prints.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="start the MCP server and check its tools")
    ap.add_argument("--customer-id", help="Google Ads account to check access to (with --live)")
    ap.add_argument("--timeout", type=float, default=180, help="seconds to wait for the server to start and answer")
    args = ap.parse_args(argv)
    checks = run_checks(ROOT, live=args.live, customer_id=args.customer_id, timeout_s=args.timeout)
    print(render(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
