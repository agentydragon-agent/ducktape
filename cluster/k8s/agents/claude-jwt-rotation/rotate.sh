#!/usr/bin/bash
set -euo pipefail

# Materialize an Authentik-issued bearer JWT into a SOPS-encrypted file.
#
# Runs hourly. Most invocations are no-ops: we sparse-clone just the existing
# $SOPS_FILE + $SOPS_CONFIG, read the unencrypted-by-suffix
# `expires_unencrypted` field with sed (no SOPS decryption, no in-cluster
# age-key access), and skip rotation when remaining validity exceeds
# $ROTATE_BELOW_HOURS. So an Authentik token is actually minted only every
# ~44 days (validity 45d − 1d threshold), but a failed rotation self-heals in
# <1h.
#
# `expires_unencrypted` is set from the JWT's own `exp` claim at write-time
# below — single source of truth, no constant duplicated from Authentik
# provider config. SOPS leaves the field plaintext because it ends in the
# default unencrypted_suffix `_unencrypted`.
#
# Parameterization:
#   ROTATION_NAME            Human-readable name for logs / commits
#   AUTHENTIK_PROVIDER_SLUG  Provider slug used to verify the JWT issuer
#   TOKEN_SCOPES             OAuth scopes for the client_credentials exchange
#   SOPS_FILE                Repo path to the encrypted output file
#   TOKEN_FIELD_NAME         YAML field name for the encrypted token (jwt/token)
#   EXPECTED_GROUP           Optional JWT group claim that must be present
#   ROTATE_BELOW_HOURS       Freshness threshold before a new token is minted

: "${ROTATION_NAME:?ROTATION_NAME is required}"
: "${AUTHENTIK_PROVIDER_SLUG:?AUTHENTIK_PROVIDER_SLUG is required}"
: "${SOPS_FILE:?SOPS_FILE is required}"

ROTATE_BELOW_HOURS="${ROTATE_BELOW_HOURS:-24}"
TOKEN_SCOPES="${TOKEN_SCOPES:-openid profile email}"
TOKEN_FIELD_NAME="${TOKEN_FIELD_NAME:-jwt}"
EXPECTED_GROUP="${EXPECTED_GROUP:-}"
SOPS_CONFIG="${SOPS_CONFIG:-.sops.yaml}"
GITHUB_REPO="${GITHUB_REPO:-agentydragon/ducktape}"
TOKEN_URL="${TOKEN_URL:-https://auth.allegedly.works/application/o/token/}"
AUTHENTIK_CLIENT_DIR="${AUTHENTIK_CLIENT_DIR:-/var/run/secrets/authentik-client}"
GITHUB_PAT_FILE="${GITHUB_PAT_FILE:-/var/run/secrets/github-pat/token}"
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-authentik-jwt-rotation}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-noreply@allegedly.works}"
COMMIT_MESSAGE_PREFIX="${COMMIT_MESSAGE_PREFIX:-chore: rotate ${ROTATION_NAME}}"
EXPECTED_ISSUER="https://auth.allegedly.works/application/o/${AUTHENTIK_PROVIDER_SLUG}/"

# rules_distroless doesn't run update-ca-certificates, so /etc/ssl/certs/ is
# empty. Build a CA bundle from the raw cert files for git/libcurl.
CA_BUNDLE="/tmp/ca-bundle.crt"
cat /usr/share/ca-certificates/mozilla/*.crt >"$CA_BUNDLE"
export GIT_SSL_CAINFO="$CA_BUNDLE"
export CURL_CA_BUNDLE="$CA_BUNDLE"

CLIENT_ID=$(cat "${AUTHENTIK_CLIENT_DIR}/client_id")
CLIENT_SECRET=$(cat "${AUTHENTIK_CLIENT_DIR}/client_secret")
GITHUB_PAT=$(cat "$GITHUB_PAT_FILE")

# Decode a JWT's base64url-encoded payload to JSON on stdout.
# (base64 needs '=' padding and '+' '/' alphabet; JWT uses '-' '_' and no padding.)
decode_jwt_payload() {
  local jwt="$1"
  local p
  p=$(printf '%s' "$jwt" | cut -d. -f2 | tr '_-' '/+')
  case $((${#p} % 4)) in
    2) p="${p}==" ;;
    3) p="${p}=" ;;
  esac
  printf '%s' "$p" | base64 -d
}

# --- Sparse clone (just $SOPS_FILE + $SOPS_CONFIG, ~few KB) ---------------
# .sops.yaml is needed by `sops encrypt --in-place` later to find the right
# recipient set. The freshness check itself only needs $SOPS_FILE.
mkdir /tmp/repo
cd /tmp/repo
git init -q
git remote add origin "https://x-access-token:${GITHUB_PAT}@github.com/${GITHUB_REPO}.git"
git config core.sparseCheckout true
{
  echo "$SOPS_FILE"
  echo "$SOPS_CONFIG"
} >.git/info/sparse-checkout
git fetch -q --depth=1 --no-tags origin devel
git checkout -q FETCH_HEAD

# --- Freshness check on existing JWT (no decryption needed) ---------------
if [ -f "$SOPS_FILE" ]; then
  EXISTING_EXPIRES=$(sed -n 's/^expires_unencrypted:[[:space:]]*//p' "$SOPS_FILE" | head -n1 | tr -d '"')
  if [ -n "$EXISTING_EXPIRES" ]; then
    EXPIRES_TS=$(date -u -d "$EXISTING_EXPIRES" +%s)
    NOW_TS=$(date +%s)
    REMAINING_H=$(((EXPIRES_TS - NOW_TS) / 3600))
    if [ "$REMAINING_H" -gt "$ROTATE_BELOW_HOURS" ]; then
      echo "${ROTATION_NAME}: existing token expires at $EXISTING_EXPIRES (${REMAINING_H}h remaining > ${ROTATE_BELOW_HOURS}h threshold); skipping rotation"
      exit 0
    fi
    echo "${ROTATION_NAME}: existing token expires at $EXISTING_EXPIRES (${REMAINING_H}h remaining); rotating"
  else
    echo "${ROTATION_NAME}: existing $SOPS_FILE has no expires_unencrypted field; rotating to populate it"
  fi
else
  echo "${ROTATION_NAME}: no existing $SOPS_FILE on devel; bootstrapping initial rotation"
fi

# --- Mint a fresh JWT via client_credentials -------------------------------
JWT=$(curl -sSf -u "${CLIENT_ID}:${CLIENT_SECRET}" \
  -d grant_type=client_credentials \
  --data-urlencode "scope=${TOKEN_SCOPES}" \
  "${TOKEN_URL}" | jq -r .access_token)

if [ -z "$JWT" ] || [ "$JWT" = "null" ]; then
  echo "ERROR: ${ROTATION_NAME}: client_credentials exchange returned no access_token" >&2
  exit 1
fi

# Decode payload: verify issuer / optional claims, capture exp for
# expires_unencrypted.
PAYLOAD=$(decode_jwt_payload "$JWT")
if ! printf '%s' "$PAYLOAD" | jq -e --arg issuer "$EXPECTED_ISSUER" '.iss == $issuer' >/dev/null; then
  echo "ERROR: ${ROTATION_NAME}: issued JWT has unexpected issuer (wanted ${EXPECTED_ISSUER})" >&2
  echo "payload: $PAYLOAD" >&2
  exit 1
fi
if [ -n "$EXPECTED_GROUP" ] && ! printf '%s' "$PAYLOAD" | jq -e --arg group "$EXPECTED_GROUP" '(.groups // []) | index($group)' >/dev/null; then
  echo "ERROR: ${ROTATION_NAME}: issued JWT does not carry groups: [\"${EXPECTED_GROUP}\"]" >&2
  echo "payload: $PAYLOAD" >&2
  exit 1
fi
EXP_TS=$(printf '%s' "$PAYLOAD" | jq -r '.exp')
EXPIRES_ISO=$(date -u -d "@${EXP_TS}" +%Y-%m-%dT%H:%M:%SZ)

# --- Write + commit + push -------------------------------------------------
# `expires_unencrypted` matches SOPS's default unencrypted_suffix (`_unencrypted`),
# so it stays plaintext after `sops encrypt --in-place`.
mkdir -p "$(dirname "$SOPS_FILE")"
cat >"$SOPS_FILE" <<EOF
expires_unencrypted: "$EXPIRES_ISO"
${TOKEN_FIELD_NAME}: $JWT
EOF

sops encrypt --in-place "$SOPS_FILE"

git config user.name "$GIT_AUTHOR_NAME"
git config user.email "$GIT_AUTHOR_EMAIL"
git add "$SOPS_FILE"

if git diff --cached --quiet; then
  echo "${ROTATION_NAME}: no changes to commit"
else
  git commit -q -m "${COMMIT_MESSAGE_PREFIX} ($(date -I))"
  git push -q origin HEAD:devel
fi
