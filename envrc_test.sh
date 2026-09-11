#!/usr/bin/env bash
# Exercise the real .envrc without evaluating Nix or loading developer secrets.
set -euo pipefail

envrc="${TEST_SRCDIR}/${TEST_WORKSPACE}/.envrc"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/devinfra/secrets"
printf ':\n' >"$fixture/devinfra/secrets/cli_env.sh"
cd "$fixture"

watch_file() { test "$*" = nix/artifact-pins.json; }
# The pinned devShell does not define SSL_CERT_FILE; use flake leaves it alone.
use() { test "$*" = flake; }

check_bundle() (
  local initial=$1 expected=$2
  if [[ "$initial" = unset ]]; then
    unset SSL_CERT_FILE
  else
    export SSL_CERT_FILE="$initial"
  fi
  source "$envrc"
  # A child TLS client must receive the bundle, not just the direnv shell.
  bash --noprofile --norc -c 'test "$SSL_CERT_FILE" = "$1"' _ "$expected"
)

check_bundle '/test host/trust/ca.pem' '/test host/trust/ca.pem'
check_bundle unset /etc/ssl/certs/ca-certificates.crt
check_bundle '' /etc/ssl/certs/ca-certificates.crt
