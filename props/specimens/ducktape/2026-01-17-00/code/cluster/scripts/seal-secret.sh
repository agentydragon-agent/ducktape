#!/usr/bin/env bash
# Seal a Kubernetes secret using the stable keypair from terraform state.
#
# Usage: ./scripts/seal-secret.sh <secret.yaml> <output-sealed.yaml>
#
# The sealed secrets certificate is read directly from terraform state
# in 00-persistent-auth (no file materialization needed).
#
# After sealing, you must commit the sealed secret manually:
#   git add <output-sealed.yaml> && git commit
#
# TODO: Migrate to Bazel. See //cluster/scripts:validate_sealed_secrets for pattern.
# Requires: @multitool//tools/kubeseal, @tf_toolchains//:tofu

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/terraform/00-persistent-auth"

INPUT_FILE="${1:-}"
OUTPUT_FILE="${2:-}"

if [[ -z "$INPUT_FILE" || -z "$OUTPUT_FILE" ]]; then
  echo "Usage: $0 <secret.yaml> <output-sealed.yaml>"
  echo ""
  echo "Example:"
  echo "  kubectl create secret generic my-secret --from-literal=key=value \\"
  echo "    --dry-run=client -o yaml | $0 /dev/stdin k8s/my-app/my-sealed.yaml"
  exit 1
fi

# Check if terraform state exists
if [[ ! -f "$TF_DIR/terraform.tfstate" ]]; then
  echo "❌ No terraform state found at $TF_DIR/terraform.tfstate"
  echo "   Run 'cd terraform/00-persistent-auth && terraform apply' first"
  exit 1
fi

# Get certificate from terraform state
CERT=$(cd "$TF_DIR" && terraform output -raw sealed_secrets_public_key_pem 2>/dev/null) || {
  echo "❌ Could not read sealed_secrets_public_key_pem from terraform state"
  echo "   Run 'cd terraform/00-persistent-auth && terraform apply' first"
  exit 1
}

kubeseal --cert <(echo "$CERT") --format=yaml <"$INPUT_FILE" >"$OUTPUT_FILE"
echo "✅ Sealed: $OUTPUT_FILE"
echo "📝 Commit: git add $OUTPUT_FILE && git commit"
