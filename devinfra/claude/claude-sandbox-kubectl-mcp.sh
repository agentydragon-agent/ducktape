#!/usr/bin/env bash
# Assembles a kubeconfig from CLAUDE_SANDBOX_K8S_TOKEN and runs kubernetes-mcp-server.
# The Go server uses client-go (needs a kubeconfig file, not env vars).
set -euo pipefail

if [ -z "${CLAUDE_SANDBOX_K8S_TOKEN:-}" ]; then
  echo "ERROR: CLAUDE_SANDBOX_K8S_TOKEN not set" >&2
  exit 1
fi

TMPKC="$(mktemp "${TMPDIR:-/tmp}/claude-sandbox-kc.XXXXXX")"
trap 'rm -f "$TMPKC"' EXIT

cat >"$TMPKC" <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://api.allegedly.works:16443
    insecure-skip-tls-verify: true
  name: claude-sandbox
contexts:
- context:
    cluster: claude-sandbox
    namespace: claude-sandbox
    user: claude-code-web
  name: claude-code-web
current-context: claude-code-web
users:
- name: claude-code-web
  user:
    token: ${CLAUDE_SANDBOX_K8S_TOKEN}
EOF
chmod 600 "$TMPKC"

# No exec — let bash stay alive so trap cleans up the temp kubeconfig on exit.
kubernetes-mcp-server --kubeconfig "$TMPKC" --disable-multi-cluster "$@"
