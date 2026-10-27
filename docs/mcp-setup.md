# Connecting the Google Ads MCP server (read-only)

Do this **on your own computer**, in your local clone of this repo, with Claude Code running locally.
Do not put credentials in a cloud session, in chat, or in any committed file.

Based on Google's official server, [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp),
and the [Google Ads MCP server guide](https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server)
(checked 2026-10-25). Re-check both before you start: the project is young and changes quickly.

## What gets installed, and why
| Item | Why | Where it goes |
|---|---|---|
| Python 3.10–3.13 | Runs Google's server (Homebrew `python@3.12` is fine, see Troubleshooting) | Homebrew |
| `google-ads-mcp==0.0.5` | The MCP server itself; pulls FastMCP and Google's Ads client library | Its own virtual environment, `~/.local/share/google-ads-os/mcp-venv`, not your system Python |
| `gcloud` CLI (only for option A) | Creates Application Default Credentials | Your user account |

This repo's own scripts need **no** extra packages (standard library only).

## What the server can do
Tools (v0.0.5): `search_search`, `customers_list_accessible_customers`, `metadata_get_resource_metadata`.
`search` does not take a GAQL string: it takes `customer_id`, `fields[]`, `resource`, `conditions[]`
(ANDed), `orderings[]`, `limit`, and builds the query itself. `scripts/snapshot.py` converts each
`queries/*.gaql` file into those parts and records the exact arguments sent in the snapshot. Results come
back as `{"result": [ {"campaign.id": …, "metrics.cost_micros": …}, … ]}`. The tests use the upstream tool
list copied into `tests/fixtures/upstream_golden_tools_list.json`; re-copy it whenever you change the pinned version. Google's documentation lists no write tools. This repo adds two more
layers: `scripts/gads/connect/mcp_client.py` refuses any tool outside a read-only allowlist, and
`.claude/settings.json` denies the GoMarble connector in this project.

## Which OAuth method
| | **A. Application Default Credentials (recommended)** | **B. FastMCP OAuth proxy** | C. `google-ads.yaml` |
|---|---|---|---|
| Sign-in | Once, in your browser, via `gcloud` | Each MCP client signs in through the browser | Existing client-library config |
| Server runs | Locally, started by Claude Code / the scripts | As a separate web service (`http://localhost:8080/mcp` or Cloud Run) | Locally |
| Works with this repo's scripts | **Yes** | Not yet (scripts start a local process only) | Yes, but needs an upstream code edit |
| Best for | You and a few users, each on their own machine | Teams, claude.ai web/mobile, shared deployment | Existing API users |

The steps below use **A**.

## Fast path on a Mac
After steps 2–4 (Cloud project, consent screen, Desktop app client), run from the repo folder:
```bash
bash scripts/setup_mac.sh --project-id YOUR_PROJECT_ID
```
It does steps 1, 5, 7 and 8 for you, and optionally adds the server to Claude Desktop:
- checks Python and `gcloud`, and **asks before** installing any of them with Homebrew
  (`python@3.12`, `--cask gcloud-cli`); if Homebrew itself is missing it stops and points you to brew.sh;
- **asks before** installing Google's server, pinned to `google-ads-mcp==0.0.5`, into its own virtual environment
  at `~/.local/share/google-ads-os/mcp-venv` (outside the repo; installed once, not re-downloaded on each start);
- moves the newest `~/Downloads/client_secret*.json` to `~/.config/google-ads-os/client_secret.json` (after asking),
  checks it is a *Desktop app* client and makes it private (`chmod 600`);
- runs the browser sign-in (or keeps your existing sign-in if you answer No), then writes `.mcp.json` (private,
  absolute path of the server's `google-ads-mcp` command, no developer token) and runs `check_connection.py --live`;
- backs up any `.mcp.json` or Claude Desktop config before changing it (`*.bak-<timestamp>`), and replaces an
  older `pipx run` entry only after asking.

It is safe to re-run: finished steps are kept, and identical files are not rewritten. It never prints secrets.
Tested on Linux with stand-in `brew`/`gcloud` and a synthetic server package; the first real run is on your Mac,
so read each prompt. The config writer is `scripts/setup_config.py` (also usable on its own).

## Steps (option A)
1. **Install the tools**: Python 3.10–3.13, the [gcloud CLI](https://cloud.google.com/sdk/docs/install), and
   clone this repo. Then install Google's server in its own environment (macOS/Linux):
   ```bash
   python3 scripts/setup_config.py server-venv --python "$(command -v python3.12)"
   ```
   It prints the server command, `~/.local/share/google-ads-os/mcp-venv/bin/google-ads-mcp`. (Elsewhere:
   `python -m venv <dir>`, then `<dir>/bin/pip install google-ads-mcp==0.0.5`; on Windows the command is
   `<dir>\Scripts\google-ads-mcp.exe`.)
2. **Google Cloud project**: create or choose one and enable the **Google Ads API**.
3. **OAuth consent screen**:
   - **Audience**: choose *Internal* if you use Google Workspace and every user is in your domain;
     otherwise *External*, and add each user's Google account as a test user.
   - **Publishing status**: refresh tokens for apps left in **Testing** expire after **7 days**, so everyone
     would have to sign in again weekly. Publish the app to *In production* to avoid that, then have each
     user sign in again once (tokens issued while in Testing keep the 7-day limit).
4. **OAuth client**: create a client ID of type **Desktop app** and download its JSON. Keep it outside
   the repo, e.g. `~/.config/google-ads-os/client_secret.json`.
5. **Sign in once**:
   ```bash
   gcloud auth application-default login \
     --scopes https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform \
     --client-id-file=$HOME/.config/google-ads-os/client_secret.json
   ```
   Use the Google account that has access to the Ads account, then note the printed
   `Credentials saved to file: [...]` path.
6. **Developer token**: the upstream README marks it optional ("if your setup requires"). Try without it.
   If the API returns a developer-token error, request one in the Google Ads API Center (production
   accounts need at least Explorer access).
7. **Configure Claude Code**:
   ```bash
   cp .mcp.json.example .mcp.json      # .mcp.json is gitignored
   ```
   - Set `command` to the absolute path of the server command from step 1, and keep `"args": []`.
   - Set `GOOGLE_APPLICATION_CREDENTIALS` to the path from step 5 and `GOOGLE_PROJECT_ID` to your project.
   - Delete `GOOGLE_ADS_DEVELOPER_TOKEN` if you have none; prefer `"${GOOGLE_ADS_DEVELOPER_TOKEN}"` over a
     literal value if you do (Claude Code and `scripts/snapshot.py` both expand `${VAR}`).
   - Delete `GOOGLE_ADS_LOGIN_CUSTOMER_ID` unless you access the account through a manager (MCC) account.
8. **Check the setup**:
   ```bash
   python3 scripts/check_connection.py                                   # configuration, no network
   python3 scripts/check_connection.py --live --customer-id 123-456-7890 # starts the server, checks access
   ```
   It checks `.mcp.json` (no placeholders, ignored by git), the launcher, the credentials file (type,
   refresh token, file permissions, location outside the repo), the server's tool contract, and whether
   your login can see the account. It never prints secret values.
9. **First-connection check**: `python3 scripts/first_connect.py --customer-id <ID>` fetches every query in
   `queries/` once (read-only), runs the contract gate on each response and reports which features can run
   (`outputs/first-connect_*/report.md`). The report holds field names, counts and statuses only, so you can share
   it if something fails. For a single query: `scripts/snapshot.py` then `scripts/inspect_snapshot.py`.
10. In Claude Code, run `/mcp` to confirm the server is connected, then say **"run onboarding"**.

## Troubleshooting

### macOS 26.0–26.2: "server exited during initialize", or pip fails with `invalid literal for int() with base 10: ''`
**Cause.** Homebrew's current Python bottles are built for macOS 26.3 and later. On macOS 26.0–26.2 their
`pyexpat` module cannot load (`Symbol not found: _XML_SetAllocTrackerActivationThreshold` in
`/usr/lib/libexpat.1.dylib`); Homebrew's maintainers call this an unsupported configuration and advise updating
macOS ([homebrew-core #277086](https://github.com/Homebrew/homebrew-core/issues/277086),
[#277330](https://github.com/Homebrew/homebrew-core/issues/277330)). Without `pyexpat`, `plistlib` cannot be
imported, so `platform.mac_ver()` quietly returns `''` even though `SystemVersion.plist` is fine. pip then crashes
in its vendored `truststore` (and in `packaging`'s wheel-tag code), both of which do `int('')`. That breaks
`python -m venv` (via `ensurepip`), `pipx run` (its shared environment is built with `ensurepip`), and any
`pip install`. `--python` for pipx does not help, and `PIP_USE_DEPRECATED=legacy-certs` alone does not either:
`ensurepip` strips every `PIP_*` variable, and the wheel-tag code still fails.

**Check** (safe, prints no secrets):
```bash
/opt/homebrew/bin/python3.12 -c "import pyexpat"          # fails with "Symbol not found" on affected Macs
/opt/homebrew/bin/python3.12 -c "import platform; print(repr(platform.mac_ver()[0]))"   # '' when affected
```

**What `setup_mac.sh` does about it.** It never uses `ensurepip` or `pipx`. It creates the server's environment
with `python -m venv --without-pip`, puts a small shim in it (`scripts/gads/connect/macver_shim.py`: when `mac_ver()` is
empty on macOS, it reads `ProductVersion` from `SystemVersion.plist` without an XML parser), and runs the pip wheel
that ships with that Python to install the pinned server. The shim affects only that environment; your Python is
not modified. The real fix is to update macOS to 26.3 or later; after that the shim does nothing.

**Leftovers from the older `pipx run` setup** are harmless. You can delete pipx's half-built shared environment
(`rm -rf ~/Library/Application\ Support/pipx/shared`) and, if you no longer use pipx, `brew uninstall pipx`.

## Adding other users
Anyone can use this system with their own access: a colleague, an agency or freelancer, a consultant,
or someone from the client side. The rule is **one person, one Google login, one set of credentials**.
Never share your credentials file, refresh token, or `.mcp.json`.

### Option A: each user on their own machine
| Step | Who | What |
|---|---|---|
| 1. Google Ads access | An account **Admin** | Invite the user's Google account (Admin → Access and security). Give the lowest level that works: **Read-only** is designed for viewing campaigns and reports and cannot edit campaigns. Confirm with their `--live` check. Avoid Standard or Admin for analysis-only users. |
| 2. OAuth consent | You (Cloud project owner) | *External* audience in Testing: add their Google account as a test user. *Internal*: nothing to do if they are in your Workspace domain. Published app: nothing to do. |
| 3. OAuth client JSON | You | Share it privately (password manager or direct transfer), never via the repo, chat logs, or email threads that get forwarded. Desktop-app client secrets are not strong secrets on their own, but they identify your project. |
| 4. Developer token (only if required) | You | It is one token per company. Each user would need a copy in their environment (`${GOOGLE_ADS_DEVELOPER_TOKEN}`), which spreads a shared secret. If many users need it, prefer option B. |
| 5. Repo access | You | Add them on GitHub (private repo). They receive the shared `context/` business facts and skills; their own snapshots and reports stay on their machine (`data/` and `outputs/` are gitignored). Check `context/` holds nothing they should not see. |
| 6. Their setup | The user | Steps 1, 5, 7, 8, 9 above with their own Google account and their own Claude account. |

**Users from another company (agency, freelancer)**: if they manage accounts through their own manager
(MCC) account, link the account to their manager instead of inviting individuals, and they set
`GOOGLE_ADS_LOGIN_CUSTOMER_ID` to their manager ID. Agree in writing on what they may change. This repo
is read-only, but their Google Ads access level decides what they can do elsewhere.

### Option B: a shared server (later)
One server (e.g. Cloud Run with the OAuth proxy, see the upstream README) holds the OAuth client secret and
developer token; each user adds its URL in Claude and signs in with Google. Users need no gcloud and no
secrets, and this is the route for claude.ai web or mobile. This repo's scripts do not support it yet.

### Removing a user
1. Remove their Google Ads access (Admin → Access and security). This alone stops their data access.
2. Remove them as a test user (External / Testing) and from the GitHub repo.
3. They should run `gcloud auth application-default revoke` and delete their `.mcp.json`.
4. If a developer token was shared with them, consider rotating it.

## Security notes
- `.gitignore` keeps `.mcp.json`, credential files and `data/` out of commits. It is **not access control**:
  anything on your disk can still be read by local tools, including AI assistants. Keep credential files
  outside the repo, and restrict their file permissions (`chmod 600`).
- Revoke or rotate credentials if they ever appear in chat, a log, or a commit.
