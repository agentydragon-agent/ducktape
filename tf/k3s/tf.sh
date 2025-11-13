#!/bin/bash
# Wrapper script to run Terraform with secrets from Ansible Vault
# Handles both Proxmox token and Headscale API key
# Usage: ./tf.sh <terraform commands>
# Example: ./tf.sh apply

set -euo pipefail

# Path to vault file (relative to this script's location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_FILE="${SCRIPT_DIR}/../../ansible/terraform-secrets.vault"

if [[ ! -f "$VAULT_FILE" ]]; then
    echo "Error: Vault file not found at $VAULT_FILE"
    echo "Please create it with: ansible-vault create $VAULT_FILE"
    exit 1
fi

# Get vault password from keyring
VAULT_PASS=$(secret-tool lookup service ansible-vault account ducktape 2>/dev/null) || {
    echo "Error: Could not retrieve Ansible Vault password from keyring"
    echo "Ensure it's stored with: secret-tool store --label='ansible-vault ducktape' service ansible-vault account ducktape"
    exit 1
}

# Extract Proxmox token components from vault
TOKEN_ID=$(echo "$VAULT_PASS" | ansible-vault view --vault-password-file=/dev/stdin "$VAULT_FILE" 2>/dev/null | grep vault_proxmox_terraform_token_id | awk '{print $2}' | tr -d '"')
TOKEN_SECRET=$(echo "$VAULT_PASS" | ansible-vault view --vault-password-file=/dev/stdin "$VAULT_FILE" 2>/dev/null | grep vault_proxmox_terraform_token_secret | awk '{print $2}' | tr -d '"')

if [[ -z "$TOKEN_ID" ]] || [[ -z "$TOKEN_SECRET" ]]; then
    echo "Error: Could not extract Proxmox token from vault"
    echo "Ensure the vault contains:"
    echo "  vault_proxmox_terraform_token_id: \"terraform@pve!terraform-import\""
    echo "  vault_proxmox_terraform_token_secret: \"your-token-secret\""
    exit 1
fi

# Export Proxmox token
export TF_VAR_proxmox_api_token="${TOKEN_ID}=${TOKEN_SECRET}"

# Simplified - no Headscale key needed (Ansible will handle registration)

# Change to the script directory first
cd "$SCRIPT_DIR"

# Run terraform with all arguments passed through
echo "Running: terraform $*"
terraform "$@"