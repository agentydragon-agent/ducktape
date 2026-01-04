#!/usr/bin/env bash
# Validate all SealedSecrets can be decrypted with terraform keypair.
# Uses kubeseal --recovery-unseal (works offline, no cluster needed).
#
# This is called by pre-commit and bootstrap.sh to catch keypair mismatches
# before they reach the cluster.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$REPO_ROOT/terraform/00-persistent-auth"

# Check if terraform state exists
if [[ ! -f "$TF_DIR/terraform.tfstate" ]]; then
    echo "⚠️  No terraform state found at $TF_DIR/terraform.tfstate"
    echo "   Skipping SealedSecret validation (state not initialized)"
    exit 0
fi

# Extract private key from terraform state to temp file
PRIVATE_KEY_FILE=$(mktemp)
trap "rm -f $PRIVATE_KEY_FILE" EXIT

(cd "$TF_DIR" && terraform output -raw sealed_secrets_private_key_pem 2>/dev/null) > "$PRIVATE_KEY_FILE" || {
    echo "⚠️  Could not read sealed_secrets_private_key_pem from terraform state"
    echo "   Run 'terraform apply' in $TF_DIR first"
    rm -f "$PRIVATE_KEY_FILE"
    exit 1
}

# Find all SealedSecret files
SEALED_SECRETS=$(find "$REPO_ROOT/k8s" -name "*sealed*.yaml" -type f 2>/dev/null || true)

if [[ -z "$SEALED_SECRETS" ]]; then
    echo "✅ No SealedSecret files found"
    exit 0
fi

FAILED=0
CHECKED=0
for file in $SEALED_SECRETS; do
    # Check if file contains SealedSecret kind
    if ! grep -q "kind: SealedSecret" "$file" 2>/dev/null; then
        continue
    fi

    CHECKED=$((CHECKED + 1))

    # Try to decrypt with recovery-unseal
    ERROR_OUTPUT=$(kubeseal --recovery-unseal \
        --recovery-private-key "$PRIVATE_KEY_FILE" < "$file" 2>&1 >/dev/null) && RC=0 || RC=$?
    if [[ $RC -eq 0 ]]; then
        echo "✅ $file"
    else
        echo "❌ $file"
        echo "   Error: $ERROR_OUTPUT"
        FAILED=1
    fi
done

if [[ $CHECKED -eq 0 ]]; then
    echo "✅ No SealedSecret files found"
    exit 0
fi

if [[ $FAILED -eq 1 ]]; then
    echo ""
    echo "ERROR: Some SealedSecrets cannot be decrypted with the terraform keypair"
    echo "Run 'cd terraform/00-persistent-auth && terraform apply' to re-seal"
    exit 1
fi

echo ""
echo "✅ All $CHECKED SealedSecrets validated successfully"
