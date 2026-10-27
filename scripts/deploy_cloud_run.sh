#!/usr/bin/env bash
# Deploys Google's read-only Google Ads MCP server to Cloud Run, so claude.ai (web, Desktop and mobile) can use it
# as a custom connector. Run it in Google Cloud Shell (shell.cloud.google.com): gcloud and git are already there.
#
#   bash scripts/deploy_cloud_run.sh --project-id YOUR_PROJECT_ID [--region us-central1] [--dry-run]
#
# What it does (asks before each step that changes your project; re-running is safe):
#   1. checks billing is enabled and turns on the APIs it needs (Cloud Run, Cloud Build, Artifact Registry,
#      Firestore, Secret Manager, Google Ads API);
#   2. builds google-ads-mcp 0.0.5 (Google's code, pinned tag) with Firestore support, into Artifact Registry;
#   3. creates a Firestore database (keeps sign-ins across restarts) and a dedicated service account;
#   4. stores the Web OAuth client secret and a generated signing key in Secret Manager (never on the command line);
#   5. deploys the service (public address; Google sign-in is the gate) and checks it answers.
# --dry-run prints every gcloud command instead of running it. Secrets are never printed. See docs/hosted-connector.md.
set -euo pipefail

UPSTREAM="https://github.com/googleads/google-ads-mcp"
TAG="v0.0.5"
SERVICE="google-ads-mcp"
REPO="mcp-servers"
SA_NAME="google-ads-mcp"
PROJECT_ID=""
REGION="us-central1"
FIRESTORE_LOCATION="nam5"
DRY_RUN=0
APIS="run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com googleads.googleapis.com"

while [ $# -gt 0 ]; do
  case "$1" in
    --project-id) [ $# -ge 2 ] || { echo "--project-id needs a value" >&2; exit 2; }; PROJECT_ID="$2"; shift 2 ;;
    --region) [ $# -ge 2 ] || { echo "--region needs a value" >&2; exit 2; }; REGION="$2"; shift 2 ;;
    --firestore-location) [ $# -ge 2 ] || { echo "--firestore-location needs a value" >&2; exit 2; }; FIRESTORE_LOCATION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
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
run() {  # changes something: printed in --dry-run, executed otherwise
  if [ "$DRY_RUN" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi
}

command -v gcloud >/dev/null 2>&1 || stop "gcloud not found. Open Google Cloud Shell (shell.cloud.google.com) and run this there."
command -v git >/dev/null 2>&1 || stop "git not found."
[[ "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || stop "pass --project-id with your Google Cloud project ID."
[[ "$REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] || stop "--region looks wrong: $REGION"

echo "Google Ads MCP server -> Cloud Run (read-only). Project $PROJECT_ID, region $REGION.$([ "$DRY_RUN" = 1 ] && echo ' DRY RUN.')"

step "1/6 Project, billing and APIs"
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "$ACCOUNT" ] || stop "gcloud is not signed in. Run: gcloud auth login"
ok "signed in to gcloud"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || true)"
[ -n "$PROJECT_NUMBER" ] || stop "cannot read project $PROJECT_ID (wrong ID, or this Google account has no access)."
BILLING="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || true)"
if [ "$BILLING" != "True" ] && [ "$BILLING" != "true" ]; then
  stop "billing is not enabled for $PROJECT_ID. Console: Billing -> link a billing account, and set a budget alert (Billing -> Budgets & alerts, e.g. 1 EUR). Then re-run."
fi
ok "billing enabled"
if ask_yes "   Enable the APIs this needs ($APIS)?"; then
  # shellcheck disable=SC2086
  run gcloud services enable $APIS --project "$PROJECT_ID"
else
  stop "the APIs are required."
fi

URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
CALLBACK="${URL}/auth/callback"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${TAG#v}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

step "2/6 Web OAuth client"
cat <<EOF
   Create (or reuse) an OAuth client of type "Web application" for this server:
   Google Cloud console -> Google Auth Platform -> Clients -> Create client -> Web application.
   Authorized redirect URIs - add both:
     $CALLBACK
     https://claude.ai/api/mcp/auth_callback
   Keep the consent screen's Audience in "Testing" and list every Google account allowed to connect
   as a test user (only they can sign in; sign-ins expire after 7 days in Testing).
EOF
CLIENT_ID=""
for _ in 1 2 3; do
  printf '   Web client ID (ends with .apps.googleusercontent.com): '
  read -r CLIENT_ID || CLIENT_ID=""
  [[ "$CLIENT_ID" =~ ^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$ ]] && break
  echo "   That does not look like a client ID."
  CLIENT_ID=""
done
[ -n "$CLIENT_ID" ] || stop "no valid Web client ID entered."
ok "client ID received"

step "3/6 Build Google's server (pinned $TAG) into Artifact Registry"
if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  ask_yes "   Create Artifact Registry repository '$REPO' in $REGION?" || stop "a repository is needed for the image."
  run gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION" --project "$PROJECT_ID"
fi
if gcloud artifacts docker images describe "$IMAGE" --project "$PROJECT_ID" >/dev/null 2>&1 && \
   ! ask_yes "   Image $IMAGE already exists. Rebuild it?"; then
  ok "using existing image"
else
  ask_yes "   Build $IMAGE with Cloud Build (a few minutes)?" || stop "the image is needed."
  SRC="$(mktemp -d)"
  trap 'rm -rf "$SRC"' EXIT
  git clone --quiet --depth 1 --branch "$TAG" "$UPSTREAM" "$SRC/google-ads-mcp"
  DOCKERFILE="$SRC/google-ads-mcp/Dockerfile"
  grep -q '^RUN uv pip install --system \.$' "$DOCKERFILE" || stop "upstream Dockerfile changed; update this script (expected 'RUN uv pip install --system .')."
  # The Firestore storage backend is an optional extra upstream; Cloud Run needs it to keep sign-ins.
  sed -i.bak 's/^RUN uv pip install --system \.$/RUN uv pip install --system ".[firestore]"/' "$DOCKERFILE"
  run gcloud builds submit "$SRC/google-ads-mcp" --tag "$IMAGE" --project "$PROJECT_ID"
fi
ok "image $IMAGE"

step "4/6 Firestore and service account"
if ! gcloud firestore databases describe --database='(default)' --project "$PROJECT_ID" >/dev/null 2>&1; then
  ask_yes "   Create the Firestore database (default) in $FIRESTORE_LOCATION (stores sign-in state only)?" || stop "Firestore is needed so sign-ins survive restarts."
  run gcloud firestore databases create --database='(default)' --location="$FIRESTORE_LOCATION" --type=firestore-native --project "$PROJECT_ID"
fi
ok "Firestore database"
if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  ask_yes "   Create service account $SA_NAME for the server?" || stop "a service account is needed."
  run gcloud iam service-accounts create "$SA_NAME" --display-name "Google Ads MCP server" --project "$PROJECT_ID"
fi
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role roles/datastore.user --condition=None --quiet >/dev/null
ok "service account $SA (Firestore access only)"

step "5/6 Secrets (Secret Manager)"
put_secret() {  # $1 = name; value read from stdin, never from arguments
  if ! gcloud secrets describe "$1" --project "$PROJECT_ID" >/dev/null 2>&1; then
    run gcloud secrets create "$1" --replication-policy=automatic --project "$PROJECT_ID" >/dev/null
  fi
  if [ "$DRY_RUN" = 1 ]; then cat >/dev/null; printf '   [dry-run] gcloud secrets versions add %s --data-file=-  (value hidden)\n' "$1"
  else gcloud secrets versions add "$1" --data-file=- --project "$PROJECT_ID" >/dev/null; fi
  run gcloud secrets add-iam-policy-binding "$1" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --project "$PROJECT_ID" --quiet >/dev/null
}
if gcloud secrets describe google-ads-mcp-client-secret --project "$PROJECT_ID" >/dev/null 2>&1 && \
   ! ask_yes "   A client secret is already stored. Replace it (e.g. new client or rotated secret)?"; then
  ok "keeping stored client secret"
else
  printf '   Web client secret (typing is hidden): '
  read -rs CLIENT_SECRET || CLIENT_SECRET=""
  echo
  [ -n "$CLIENT_SECRET" ] || stop "no client secret entered."
  printf '%s' "$CLIENT_SECRET" | put_secret google-ads-mcp-client-secret
  unset CLIENT_SECRET
  ok "client secret stored"
fi
if gcloud secrets describe google-ads-mcp-jwt-key --project "$PROJECT_ID" >/dev/null 2>&1; then
  ok "keeping signing key"
else
  # Signs the server's own tokens and (derived) encrypts stored sign-ins. Rotating it signs everyone out.
  python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | put_secret google-ads-mcp-jwt-key
  ok "signing key generated and stored"
fi

step "6/6 Deploy"
ask_yes "   Deploy $SERVICE to Cloud Run at $URL (public address; Google sign-in required)?" || stop "not deployed."
run gcloud run deploy "$SERVICE" --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$SA" --allow-unauthenticated --min-instances 0 --max-instances 2 --memory 512Mi \
  --set-env-vars "GOOGLE_PROJECT_ID=${PROJECT_ID},GOOGLE_ADS_MCP_OAUTH_CLIENT_ID=${CLIENT_ID},GOOGLE_ADS_MCP_BASE_URL=${URL},GOOGLE_ADS_MCP_STORAGE_TYPE=firestore,GOOGLE_ADS_MCP_STORAGE_FIRESTORE_PROJECT=${PROJECT_ID},FASTMCP_HOST=0.0.0.0" \
  --set-secrets "GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET=google-ads-mcp-client-secret:latest,GOOGLE_ADS_MCP_JWT_SIGNING_KEY=google-ads-mcp-jwt-key:latest"

if [ "$DRY_RUN" = 0 ]; then
  ACTUAL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)' 2>/dev/null || true)"
  if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$URL" ]; then
    echo "   Note: Cloud Run reports $ACTUAL; both addresses reach the same service. The server uses $URL."
  fi
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "$URL/.well-known/oauth-authorization-server" || true)"
  [ "$CODE" = "200" ] && ok "server answers (sign-in metadata reachable)" || \
    echo "   Warning: sign-in metadata returned HTTP $CODE; check: gcloud run services logs read $SERVICE --region $REGION --project $PROJECT_ID"
fi

cat <<EOF

Done. Connector address:  ${URL}/mcp

In claude.ai: Settings -> Connectors -> Add custom connector -> paste the address -> Add -> Connect,
then sign in with a Google account listed as a test user. The connector then also works in the Claude
Desktop and mobile apps. Add the Project instructions from docs/hosted-connector.md to your Google Ads Project.
EOF
