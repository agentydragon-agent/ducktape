#!/usr/bin/env bash
# Extract K8s cluster credentials from a Talos control plane node.
# Called by Terraform data "external" — outputs JSON on stdout.
#
# Required env vars:
#   CP_NODE       — IP or hostname of a Talos control plane node
#   TALOSCONFIG   — path to talosconfig file
set -euo pipefail

# Terraform data "external" sends query JSON on stdin — consume it
cat > /dev/null

: "${CP_NODE:?CP_NODE env var required (control plane IP)}"
: "${TALOSCONFIG:?TALOSCONFIG env var required (path to talosconfig)}"

if ! command -v talosctl &>/dev/null; then
  echo "talosctl not found in PATH" >&2
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "jq not found in PATH" >&2
  exit 1
fi

# Extract bootstrap kubeconfig (uses https://localhost:7445 — correct for HAProxy)
BOOTSTRAP_KUBECONFIG=$(talosctl -n "$CP_NODE" --talosconfig "$TALOSCONFIG" \
  cat /etc/kubernetes/bootstrap-kubeconfig) || {
  echo "Failed to extract bootstrap kubeconfig from $CP_NODE" >&2
  exit 1
}

# Extract CA certificate
CA_CERT=$(talosctl -n "$CP_NODE" --talosconfig "$TALOSCONFIG" \
  cat /etc/kubernetes/pki/ca.crt) || {
  echo "Failed to extract CA cert from $CP_NODE" >&2
  exit 1
}

# Extract cluster identity from machine configuration
MACHINE_CONFIG=$(talosctl -n "$CP_NODE" --talosconfig "$TALOSCONFIG" \
  get mc -o yaml) || {
  echo "Failed to extract machine configuration from $CP_NODE" >&2
  exit 1
}

CLUSTER_ID=$(echo "$MACHINE_CONFIG" | yq -r '.spec.cluster.id')
CLUSTER_SECRET=$(echo "$MACHINE_CONFIG" | yq -r '.spec.cluster.secret')

if [ -z "$CLUSTER_ID" ] || [ "$CLUSTER_ID" = "null" ]; then
  echo "cluster.id is empty or null in machine configuration" >&2
  exit 1
fi
if [ -z "$CLUSTER_SECRET" ] || [ "$CLUSTER_SECRET" = "null" ]; then
  echo "cluster.secret is empty or null in machine configuration" >&2
  exit 1
fi

# Output as JSON (jq --arg handles multi-line string escaping)
jq -n \
  --arg bootstrap_kubeconfig "$BOOTSTRAP_KUBECONFIG" \
  --arg ca_cert "$CA_CERT" \
  --arg cluster_id "$CLUSTER_ID" \
  --arg cluster_secret "$CLUSTER_SECRET" \
  '{
    bootstrap_kubeconfig: $bootstrap_kubeconfig,
    ca_cert: $ca_cert,
    cluster_id: $cluster_id,
    cluster_secret: $cluster_secret
  }'
