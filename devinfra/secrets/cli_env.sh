#!/usr/bin/env bash
# Laptop environment: common dev secrets only.
# Usage: eval "$(devinfra/secrets/cli_env.sh)"
#
# Does NOT export GITHUB_TOKEN or K8S_TOKEN — preserves personal tokens
# from home-manager / NixOS.
#
# Consumed by:
#   - Root .envrc (direnv)
#   - Session start hook (CLI profile)

# shellcheck source=_common.sh
source "$(dirname "$0")/_common.sh"

# No additional secrets — personal GITHUB_TOKEN and KUBECONFIG are preserved.
