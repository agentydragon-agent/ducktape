#!/usr/bin/bash
set -euo pipefail

# Materialize an Attic-issued bearer JWT into a SOPS-encrypted file.
#
# Runs hourly. Most invocations are no-ops: we sparse-clone just the existing
# $SOPS_FILE + $SOPS_CONFIG, read the unencrypted-by-suffix
# `expires_unencrypted` field with sed (no SOPS decryption, no in-cluster
# age-key access), and skip rotation when remaining validity exceeds
# $ROTATE_BELOW_HOURS. With 1-year validity and a 24h threshold, a real
# rotation happens ~once per year; failed rotations self-heal in <1h.
#
# `expires_unencrypted` is set from the JWT's own `exp` claim at write-time
# below — single source of truth, no constant duplicated from atticadm
# arguments. SOPS leaves the field plaintext because it ends in the default
# unencrypted_suffix `_unencrypted`.
#
# JWT minting goes through `kubectl exec deploy/attic -n nix-cache --
# atticadm make-token …`, so the HS256 signing secret never leaves the
# attic pod. The rotator's ServiceAccount only needs `pods/exec` on the
# attic deployment in the nix-cache namespace.
#
# Parameterization (all required unless noted):
#   ROTATION_NAME      Human-readable name for logs / commits
#   SOPS_FILE          Repo path to the encrypted output file
#   TOKEN_SUB          JWT subject claim (e.g. wyrm2, claude-web)
#   TOKEN_VALIDITY     atticadm --validity argument (e.g. "1 year")
#   ATTICADM_PULL      Space-separated cache patterns to grant pull on
#   ATTICADM_PUSH      Space-separated cache patterns to grant push on
#   TOKEN_FIELD_NAME   YAML field for the encrypted token (default attic_token)
#   ROTATE_BELOW_HOURS Freshness threshold in hours (default 24)

: "${ROTATION_NAME:?ROTATION_NAME is required}"
: "${SOPS_FILE:?SOPS_FILE is required}"
: "${TOKEN_SUB:?TOKEN_SUB is required}"
: "${TOKEN_VALIDITY:?TOKEN_VALIDITY is required}"

ATTICADM_PULL="${ATTICADM_PULL:-}"
ATTICADM_PUSH="${ATTICADM_PUSH:-}"
TOKEN_FIELD_NAME="${TOKEN_FIELD_NAME:-attic_token}"
ROTATE_BELOW_HOURS="${ROTATE_BELOW_HOURS:-24}"
SOPS_CONFIG="${SOPS_CONFIG:-.sops.yaml}"
GITHUB_REPO="${GITHUB_REPO:-agentydragon/ducktape}"
GITHUB_PAT_FILE="${GITHUB_PAT_FILE:-/var/run/secrets/github-pat/token}"
ATTIC_NAMESPACE="${ATTIC_NAMESPACE:-nix-cache}"
ATTIC_DEPLOYMENT="${ATTIC_DEPLOYMENT:-deploy/attic}"
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-attic-jwt-rotation}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-noreply@allegedly.works}"
COMMIT_MESSAGE_PREFIX="${COMMIT_MESSAGE_PREFIX:-chore: rotate ${ROTATION_NAME}}"

# rules_distroless doesn't run update-ca-certificates, so /etc/ssl/certs/ is
# empty. Build a CA bundle from the raw cert files for git/libcurl.
CA_BUNDLE="/tmp/ca-bundle.crt"
cat /usr/share/ca-certificates/mozilla/*.crt >"$CA_BUNDLE"
export GIT_SSL_CAINFO="$CA_BUNDLE"
export CURL_CA_BUNDLE="$CA_BUNDLE"

GITHUB_PAT=$(cat "$GITHUB_PAT_FILE")

# Decode a JWT's base64url-encoded payload to JSON on stdout.
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

# --- Mint a fresh JWT via atticadm running inside the attic pod ----------
declare -a atticadm_args
atticadm_args=(make-token --sub "$TOKEN_SUB" --validity "$TOKEN_VALIDITY")
for pattern in $ATTICADM_PULL; do atticadm_args+=(--pull "$pattern"); done
for pattern in $ATTICADM_PUSH; do atticadm_args+=(--push "$pattern"); done

# atticadm needs an explicit config file (without it, it tries to read a
# default config and fails with EACCES). The running attic pod has its
# own server.toml mounted at /config; reuse that.
JWT=$(kubectl -n "$ATTIC_NAMESPACE" exec "$ATTIC_DEPLOYMENT" -- \
  atticadm -f /config/server.toml "${atticadm_args[@]}" | tr -d '[:space:]')

if [ -z "$JWT" ]; then
  echo "ERROR: ${ROTATION_NAME}: atticadm make-token returned empty output" >&2
  exit 1
fi

# Sanity-check the JWT shape and extract the exp claim authoritatively.
PAYLOAD=$(decode_jwt_payload "$JWT")
if ! EXP_TS=$(printf '%s' "$PAYLOAD" | jq -er '.exp'); then
  echo "ERROR: ${ROTATION_NAME}: JWT payload missing exp claim" >&2
  echo "payload: $PAYLOAD" >&2
  exit 1
fi
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
