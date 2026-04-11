#!/usr/bin/env bash
# CI environment: common secrets + machine-user identity + registry/release credentials.
# Usage: eval "$(devinfra/secrets/ci_env.sh)"
#
# Consumed by:
#   - .github/actions/setup-ci-secrets (GitHub Actions)

# shellcheck source=_common.sh
source "$(dirname "$0")/_common.sh"

# Machine-user GitHub PAT (agentydragon-agent)
try_export GITHUB_TOKEN "$REPO_ROOT/secrets/github-pat-agentydragon-agent.yaml" '["github_token"]'

# Attic binary cache token
try_export ATTIC_TOKEN "$REPO_ROOT/secrets/ci/attic-token.sops.yaml" '["token"]'

# Harbor CI robot
try_export PROPS_REGISTRY_USERNAME "$REPO_ROOT/secrets/ci/harbor-ci-robot.sops.yaml" '["username"]'
try_export PROPS_REGISTRY_PASSWORD "$REPO_ROOT/secrets/ci/harbor-ci-robot.sops.yaml" '["password"]'

# GHCR (crane push, package visibility)
try_export GHCR_USERNAME "$REPO_ROOT/secrets/ci/ghcr-credentials.sops.yaml" '["username"]'
try_export GHCR_TOKEN "$REPO_ROOT/secrets/ci/ghcr-credentials.sops.yaml" '["token"]'

# GitHub releases (agentydragon account, contents:write on ducktape)
try_export GH_RELEASE_PAT "$REPO_ROOT/secrets/ci/gh-release-pat.sops.yaml" '["token"]'
