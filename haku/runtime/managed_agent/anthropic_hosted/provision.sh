#!/usr/bin/env bash
# Provision Haku's Anthropic-hosted (cloud) Managed Agents control plane via the
# `ant` CLI. Run from the cluster direnv (so SOPS_AGE_KEY decrypts the haku
# token) with an org ANTHROPIC_API_KEY / `ant auth login` profile. First-time
# create only; iterate later with `ant beta:agents update` /
# `ant beta:deployments update`.
#
# v0 (Path B): the cloud agent reaches the cluster over kubeapi.allegedly.works
# with the haku k8s token (secrets/haku-k8s-jwt.yaml — group=haku,
# aud=kubectl-sandbox-client-credentials, which kube-apiserver already accepts),
# injected as KUBE_TOKEN by a vault credential. No in-cluster worker, no MCP.
# (The k8s-MCP path needs a token with aud=kubectl-sandbox-mcp; see PLAN.md.)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(git -C "$here" rev-parse --show-toplevel)"

ENV_ID=$(ant beta:environments create --transform id -r <"$here/haku.environment.yaml")
echo "environment: $ENV_ID"

AGENT_ID=$(ant beta:agents create --transform id -r <"$here/haku.agent.yaml")
echo "agent: $AGENT_ID"

# Vault: the haku k8s bearer, injected as the KUBE_TOKEN env var and substituted
# ONLY on requests to kubeapi.allegedly.works — so the open v0 egress can't leak
# it. Piped via stdin, never argv. The token is rotated in-cluster by
# authentik-jwt-rotation -> secrets/haku-k8s-jwt.yaml; until that CronJob also
# pushes the vault (TODO), re-run a credential update before its expiry.
VAULT_ID=$(ant beta:vaults create --display-name haku-cloud --transform id -r)
echo "vault: $VAULT_ID"
KUBE_TOKEN=$(sops -d --extract '["jwt"]' "$repo/secrets/haku-k8s-jwt.yaml")
ant beta:vaults:credentials create --vault-id "$VAULT_ID" >/dev/null <<YAML
display_name: haku k8s bearer (kubeapi)
auth:
  type: environment_variable
  secret_name: KUBE_TOKEN
  secret_value: ${KUBE_TOKEN}
  networking:
    type: limited
    allowed_hosts: [kubeapi.allegedly.works]
YAML
echo "  -> KUBE_TOKEN credential stored in vault $VAULT_ID"

DEPL_ID=$(ant beta:deployments create \
  --agent "$AGENT_ID" --environment-id "$ENV_ID" --vault-id "$VAULT_ID" \
  --transform id -r <"$here/haku.deployment.yaml")
echo "deployment: $DEPL_ID"

echo
echo "Record these IDs. Test one run (P0 — should list haku-sandbox pods):"
echo "  ant beta:deployments run --deployment-id $DEPL_ID"
echo "Watch in the Console: platform.claude.com/workspaces/default/sessions"
