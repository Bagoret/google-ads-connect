# Connecting the Google Ads MCP server (read-only)

Do this **on your own computer**, in your local clone of this repo, with Claude Code running locally.
Do not put credentials in a cloud session, in chat, or in any committed file.

Based on Google's official server, [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp),
and the [Google Ads MCP server guide](https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server)
(checked 2026-10-25). Re-check both before you start: the project is young and changes quickly.

## What gets installed, and why
| Item | Why | Where it goes |
|---|---|---|
| `pipx` | Runs Python command-line apps in isolated environments | Your user account |
| `google-ads-mcp` (via `pipx run`) | The MCP server itself; pulls FastMCP and Google's Ads client library | pipx cache, not your system Python |
| `gcloud` CLI (only for option A) | Creates Application Default Credentials | Your user account |

This repo's own scripts need **no** extra packages (standard library only).

## What the server can do
Tools: `search` (GAQL queries), `list_accessible_customers`, `get_resource_metadata`. They may appear
namespaced, e.g. `search_search`. Google's documentation lists no write tools. This repo adds two more
layers: `scripts/gads/mcp_client.py` refuses any tool outside a read-only allowlist, and
`.claude/settings.json` denies the GoMarble connector in this project.

## Steps
1. **Google Cloud project.** Create or choose one and enable the Google Ads API.
2. **Pick a credential method.** These are the server's documented options:
   - **A. Application Default Credentials (simplest for local use).** The credentials must include the
     `https://www.googleapis.com/auth/adwords` scope. Follow the README's ADC instructions, which use
     `gcloud auth application-default login` with an OAuth client. Note the path of the credentials file it creates.
   - **B. OAuth proxy (Streamable HTTP).** Uses an OAuth client ID/secret and runs the server as a local
     HTTP service (`http://localhost:8080/mcp`). Use this if you prefer a browser OAuth flow per client.
   - **C. Existing `google-ads.yaml`** from the Python client library.
3. **Developer token.** Google's guide now marks it optional ("if your setup requires"); an older source
   says it is required, so confirm against current docs. Production accounts need at least Explorer access.
4. **Configure Claude Code.** In the repo root:
   ```bash
   cp .mcp.json.example .mcp.json      # .mcp.json is gitignored
   ```
   Edit `.mcp.json`. Prefer environment-variable references over literal secrets, for example
   `"GOOGLE_ADS_DEVELOPER_TOKEN": "${GOOGLE_ADS_DEVELOPER_TOKEN}"`. Both Claude Code and
   `scripts/snapshot.py` expand `${VAR}`. Delete `GOOGLE_ADS_LOGIN_CUSTOMER_ID` if you don't access the
   account through a manager (MCC) account. Placeholder values (`YOUR_…`, `PATH_TO_…`) make the scripts stop.
5. **Pin the version** once it works: replace the `git+https://…` spec with `google-ads-mcp==<version>`,
   so an upstream change can't silently alter behaviour.
6. **Verify**:
   - In Claude Code, run `/mcp` and check that `google-ads-mcp` is connected.
   - Ask Claude to list accessible customers.
   - Run `python3 scripts/snapshot.py --query customer_settings --customer-id <ID>`, then
     `python3 scripts/inspect_snapshot.py <file it printed>`. This is the **contract gate**: if the shape
     is unknown, stop and share the inspect output (not the credentials) so `normalize.py` can be adapted.
7. Run the onboarding skill.

## Security notes
- `.gitignore` keeps `.mcp.json`, credential files and `data/` out of commits. It is **not access control**:
  anything on your disk can still be read by local tools, including AI assistants. Keep credential files
  outside the repo where possible, and restrict their file permissions.
- Revoke or rotate credentials if they ever appear in chat, a log, or a commit.
