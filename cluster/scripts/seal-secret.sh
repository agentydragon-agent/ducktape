#!/usr/bin/env bash
# Seal a Kubernetes secret using the stable keypair.
#
# Usage: ./scripts/seal-secret.sh <secret.yaml> <output-sealed.yaml>
#
# The sealed secrets public certificate is read from the committed file
# at k8s/sealed-secrets/sealed-secrets-cert.pem (managed by terraform).
# Falls back to terraform state if the file is missing.
#
# After sealing, you must commit the sealed secret manually:
#   git add <output-sealed.yaml> && git commit
#
# TODO: Migrate to Bazel. See //cluster/scripts:validate_sealed_secrets for pattern.
# Requires: @multitool//tools/kubeseal, @tf_toolchains//:tofu

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CERT_FILE="$REPO_ROOT/k8s/sealed-secrets/sealed-secrets-cert.pem"
TF_DIR="$REPO_ROOT/terraform/bootstrap/persistent-auth"

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

# Prefer committed cert file; fall back to terraform state
if [[ -f "$CERT_FILE" ]]; then
  CERT_ARG="$CERT_FILE"
else
  echo "⚠️  Cert file not found at $CERT_FILE, falling back to terraform state"
  if [[ ! -f "$TF_DIR/terraform.tfstate" ]]; then
    echo "❌ No terraform state found at $TF_DIR/terraform.tfstate"
    echo "   Run 'cd terraform/bootstrap/persistent-auth && tofu apply' first"
    exit 1
  fi
  CERT=$(cd "$TF_DIR" && terraform output -raw sealed_secrets_cert_pem 2>/dev/null) || {
    echo "❌ Could not read sealed_secrets_cert_pem from terraform state"
    echo "   Run 'cd terraform/bootstrap/persistent-auth && tofu apply' first"
    exit 1
  }
  CERT_ARG=<(echo "$CERT")
fi

kubeseal --cert "$CERT_ARG" --format=yaml <"$INPUT_FILE" >"$OUTPUT_FILE"
echo "✅ Sealed: $OUTPUT_FILE"
echo "📝 Commit: git add $OUTPUT_FILE && git commit"
