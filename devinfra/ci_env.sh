#!/usr/bin/env bash
# Outputs CI environment variable exports (SOPS-decrypted secrets).
# Usage: eval "$(devinfra/ci_env.sh)"
#
# Requires: sops on PATH with a valid age key (SOPS_AGE_KEY, SOPS_AGE_KEY_FILE,
# or ~/.ssh/id_ed25519). Each secret is decrypted independently — if one fails,
# the others still get exported. Outputs nothing for secrets that fail to decrypt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Helper: decrypt a SOPS file, output an export line. No-op on failure.
try_export() {
  local var_name="$1" file="$2" extract="${3:-}"
  [ -f "$file" ] || return 0
  local value
  if [ -n "$extract" ]; then
    value=$(sops -d --extract "$extract" "$file" 2>/dev/null) || return 0
  else
    value=$(sops -d "$file" 2>/dev/null) || return 0
  fi
  printf 'export %s=%q\n' "$var_name" "$value"
}

# Docker CI mTLS
if [ -f "$REPO_ROOT/secrets/docker-ci/client-key.sops.pem" ]; then
  _dk=$(sops -d "$REPO_ROOT/secrets/docker-ci/client-key.sops.pem" 2>/dev/null) && {
    printf 'export DOCKER_CLIENT_KEY=%q\n' "$_dk"
    echo 'export DOCKER_HOST=tcp://docker-ci.allegedly.works:2376'
    echo 'export DOCKER_TLS_VERIFY=1'
  }
fi

# BuildBuddy API key
try_export BUILDBUDDY_API_KEY "$REPO_ROOT/secrets/buildbuddy.yaml" '["buildbuddy_api_key"]'

# GitHub PAT (agentydragon-agent machine user)
try_export GITHUB_TOKEN "$REPO_ROOT/secrets/github-pat-agentydragon-agent.yaml" '["github_token"]'

# Attic binary cache token
try_export ATTIC_TOKEN "$REPO_ROOT/secrets/ci/attic-token.sops.yaml" '["token"]'

# Harbor CI robot
try_export PROPS_REGISTRY_USERNAME "$REPO_ROOT/secrets/ci/harbor-ci-robot.sops.yaml" '["username"]'
try_export PROPS_REGISTRY_PASSWORD "$REPO_ROOT/secrets/ci/harbor-ci-robot.sops.yaml" '["password"]'
