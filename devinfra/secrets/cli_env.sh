#!/usr/bin/env bash
# Laptop environment: common dev secrets only.
# Usage: eval "$(devinfra/secrets/cli_env.sh)"
#
# Does NOT export GITHUB_TOKEN or K8S_TOKEN — preserves personal tokens
# from home-manager / NixOS.
#
# Age recipients: admin + all user keys (via _common.sh secrets)
#
# Consumed by:
#   - Root .envrc (direnv)
#   - Session start hook (CLI profile)

# shellcheck source=_common.sh
source "$(dirname "$0")/_common.sh"

# TODO: alloy-otlp-bearer-token.yaml is only decryptable by admin and claude-web.
# CLI env runs under personal user keys, so this will fail unless the user has admin.
try_export DUCKTAPE_OTEL_BEARER_TOKEN "$REPO_ROOT/secrets/alloy-otlp-bearer-token.yaml" '["token"]'
