#!/usr/bin/env bash
# One-time setup of the read-only Google Ads MCP connection on a Mac (docs/mcp-setup.md, option A).
#
#   bash scripts/setup_mac.sh [--project-id YOUR_PROJECT_ID]
#
# Run it in Terminal from anywhere inside this repo, after Part A (Cloud project, Google Ads API enabled,
# consent screen, Desktop app OAuth client). It:
#   1. checks Python 3.10+, pipx and the gcloud CLI, and asks before installing anything with Homebrew;
#   2. finds your OAuth client JSON and keeps it in ~/.config/google-ads-os/ (private to you);
#   3. runs the Google sign-in in your browser (Application Default Credentials);
#   4. writes .mcp.json (gitignored, private) and runs scripts/check_connection.py --live;
#   5. optionally adds the server to Claude Desktop, backing up its config first.
# It never prints secrets, never stores them in the repo, and never changes anything in Google Ads.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_DIR="$HOME/.config/google-ads-os"
CLIENT="$CLIENT_DIR/client_secret.json"
ADC="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"
SCOPES="https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform"
DESKTOP_DIR="$HOME/Library/Application Support/Claude"
PROJECT_ID=""

while [ $# -gt 0 ]; do
  case "$1" in
    --project-id) [ $# -ge 2 ] || { echo "--project-id needs a value" >&2; exit 2; }; PROJECT_ID="$2"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n== %s\n' "$1"; }
ok() { printf '   ok: %s\n' "$1"; }
stop() { printf '\nSTOP: %s\n' "$1" >&2; exit 2; }
ask_yes() {  # default is No
  local reply
  printf '%s [y/N] ' "$1"
  read -r reply || reply=""
  case "$reply" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}
prompt() {
  local reply
  printf '%s ' "$1" >&2
  read -r reply || reply=""
  printf '%s' "$reply"
}

ensure_brew() {
  command -v brew >/dev/null 2>&1 && return 0
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then eval "$("$b" shellenv)"; return 0; fi
  done
  stop "Homebrew is needed to install $1. Install it from https://brew.sh (copy the command shown there into Terminal), then re-run this script."
}

brew_install() {  # $1 = what it is, $2... = brew arguments
  local what="$1"; shift
  ask_yes "   Install $what with 'brew install $*'?" || stop "$what is required. Install it, then re-run this script."
  ensure_brew "$what"
  brew install "$@"
  hash -r
}

[ "${SETUP_UNAME:-$(uname -s)}" = "Darwin" ] || stop "this script is for macOS. On other systems follow docs/mcp-setup.md."
echo "Google Ads OS - Mac setup (read-only connection). Nothing is installed without asking."

step "1/7 Python 3.10 or newer"
PY=""
for c in python3 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "   Python 3.10+ not found (macOS's built-in python3 is often 3.9). This repo's scripts need it."
  brew_install "Python 3.12 (runs this repo's scripts)" python@3.12
  PY="$(brew --prefix)/bin/python3.12"
  [ -x "$PY" ] || stop "Python 3.12 was installed but not found at $PY."
fi
ok "$("$PY" --version) at $PY"

step "2/7 pipx (runs Google's MCP server in its own isolated environment)"
if ! command -v pipx >/dev/null 2>&1; then
  brew_install "pipx" pipx
fi
PIPX="$(command -v pipx)" || stop "pipx not found after install; open a new Terminal window and re-run."
ok "pipx at $PIPX"

step "3/7 gcloud CLI (used once, for the Google sign-in)"
if ! command -v gcloud >/dev/null 2>&1; then
  brew_install "the Google Cloud CLI" --cask gcloud-cli
fi
command -v gcloud >/dev/null 2>&1 || stop "gcloud not found after install; open a new Terminal window and re-run."
ok "gcloud at $(command -v gcloud)"

step "4/7 OAuth client file (Desktop app)"
if [ ! -f "$CLIENT" ]; then
  FOUND="$(ls -t "$HOME"/Downloads/client_secret*.json 2>/dev/null | head -n 1 || true)"
  if [ -n "$FOUND" ] && ! "$PY" "$REPO/scripts/setup_config.py" client-file "$FOUND"; then
    stop "$FOUND is not a Desktop app client file (it was left where it is). Delete or rename it, or put the right file at $CLIENT, then re-run."
  fi
  if [ -n "$FOUND" ] && ask_yes "   Found $FOUND. Move it to $CLIENT?"; then
    mkdir -p "$CLIENT_DIR"; chmod 700 "$CLIENT_DIR"
    mv "$FOUND" "$CLIENT"
  else
    stop "put the Desktop app client JSON from Part A at $CLIENT (create the folder if needed), then re-run."
  fi
fi
chmod 600 "$CLIENT"
"$PY" "$REPO/scripts/setup_config.py" client-file "$CLIENT" || exit 2
ok "Desktop app client at $CLIENT (private to you)"

step "5/7 Google Cloud project"
[ -n "$PROJECT_ID" ] || PROJECT_ID="$(prompt "   Project ID (e.g. my-project-123456):")"
"$PY" "$REPO/scripts/setup_config.py" project-id "$PROJECT_ID" || exit 2
ok "project $PROJECT_ID"

step "6/7 Google sign-in"
SIGN_IN=1
if [ -f "$ADC" ]; then
  echo "   You already have Google sign-in credentials at $ADC."
  ask_yes "   Sign in again (needed if they were made for another account or client)?" || SIGN_IN=0
fi
if [ "$SIGN_IN" = 1 ]; then
  echo "   Your browser will open. Sign in with the Google account that can see your Google Ads account."
  echo "   If Google says the app isn't verified: Advanced -> Go to <your app name>. It is your own app."
  gcloud auth application-default login --scopes="$SCOPES" --client-id-file="$CLIENT"
fi
[ -f "$ADC" ] || stop "no credentials at $ADC after sign-in."
chmod 600 "$ADC"
ok "credentials at $ADC (private to you)"

step "7/7 Configuration and connection check"
CID=""
for _ in 1 2 3; do
  CID="$("$PY" "$REPO/scripts/setup_config.py" customer-id "$(prompt "   Google Ads customer ID (10 digits, top right in Google Ads):")")" || CID=""
  [ -n "$CID" ] && break
done
[ -n "$CID" ] || stop "no valid customer ID entered."
LOGIN=""
MANAGER="$(prompt "   Manager (MCC) account ID, only if you reach this account through one (else press Enter):")"
if [ -n "$MANAGER" ]; then
  LOGIN="$("$PY" "$REPO/scripts/setup_config.py" customer-id "$MANAGER")" || exit 2
fi
ARGS=(--pipx "$PIPX" --credentials "$ADC" --project-id "$PROJECT_ID")
[ -n "$LOGIN" ] && ARGS+=(--login-customer-id "$LOGIN")

REPLACE=()
if [ -f "$REPO/.mcp.json" ]; then
  ask_yes "   .mcp.json already exists. Back it up and rewrite it?" || stop "kept your existing .mcp.json."
  REPLACE=(--replace)
fi
"$PY" "$REPO/scripts/setup_config.py" mcp-json --repo "$REPO" "${ARGS[@]}" ${REPLACE[@]+"${REPLACE[@]}"} || exit 2

echo "   Checking the connection (the first run downloads Google's server and can take a few minutes)..."
CHECK=0
"$PY" "$REPO/scripts/check_connection.py" --live --customer-id "$CID" || CHECK=$?

echo
if ask_yes "Also add Google Ads to the Claude Desktop app (config is backed up first)?"; then
  CONFIG="$DESKTOP_DIR/claude_desktop_config.json"
  if ! "$PY" "$REPO/scripts/setup_config.py" desktop --config "$CONFIG" "${ARGS[@]}"; then
    if ask_yes "   Replace the existing google-ads-mcp entry (a backup is kept)?"; then
      "$PY" "$REPO/scripts/setup_config.py" desktop --config "$CONFIG" "${ARGS[@]}" --replace || exit 2
    fi
  fi
  echo "   Then paste the Project instructions from docs/claude-desktop.md into a Claude Project."
fi

echo
if [ "$CHECK" = 0 ]; then
  echo "Done. Connection check passed. Open Claude Code in this folder, run /mcp, then say \"run onboarding\"."
else
  echo "Setup files are written, but the connection check reported a problem (see the list above)."
  echo "Fix the item marked fail, then re-run: $PY scripts/check_connection.py --live --customer-id $CID"
  exit 1
fi
