#!/usr/bin/env bash
# Web agent environment: common secrets + machine-user identity + k8s access.
# Usage: eval "$(devinfra/secrets/web_env.sh)"
#
# Consumed by:
#   - Session start hook (web profile)

# shellcheck source=_common.sh
source "$(dirname "$0")/_common.sh"

# Machine-user GitHub PAT (agentydragon-agent)
try_export GITHUB_TOKEN "$REPO_ROOT/secrets/github-pat-agentydragon-agent.yaml" '["github_token"]'

# K8s service account token (claude-code-web SA)
try_export K8S_TOKEN "$REPO_ROOT/secrets/claude-web-k8s-token.yaml" '["k8s_token"]'
