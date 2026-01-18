#!/usr/bin/env bash
# Regenerate Attic JWT token sealed secret using keypair from terraform state
#
# TODO: Migrate to Bazel. See //cluster/scripts:validate_sealed_secrets for pattern.
# Requires: @multitool//tools/kubeseal, @tf_toolchains//:tofu
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$CLUSTER_DIR/k8s/applications/nix-cache/jwt-token-sealed.yaml"
PERSISTENT_AUTH_DIR="$CLUSTER_DIR/terraform/00-persistent-auth"

# Generate token: 48 alphanumeric chars (~285 bits entropy), base64 encoded for Attic
RAW_TOKEN=$(openssl rand -base64 36 | tr -dc 'a-zA-Z0-9' | head -c 48)
JWT_TOKEN_BASE64=$(echo -n "$RAW_TOKEN" | base64)

# Get sealed-secrets public key from terraform state
cd "$PERSISTENT_AUTH_DIR"
CERT=$(terraform output -raw sealed_secrets_public_key)
cd - >/dev/null

# Create and seal the secret
cat <<EOF | kubeseal --cert <(echo "$CERT") --format=yaml >"$OUTPUT_FILE"
apiVersion: v1
kind: Secret
metadata:
  name: attic-jwt-token
  namespace: nix-cache
type: Opaque
stringData:
  jwt-token: "$JWT_TOKEN_BASE64"
EOF

echo "Created: $OUTPUT_FILE"
echo "Commit and push, then: flux reconcile kustomization nix-cache -n flux-system"
