#!/bin/sh
set -e

echo "Vault Auto-Unseal Service Starting..."

# Install kubectl
apk add --no-cache curl
curl -LO "https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl"
chmod +x kubectl
mv kubectl /usr/local/bin/

# Auto-unseal loop
while true; do
  echo "$(date): Checking Vault seal status..."
  
  # Check if Vault is responding
  if vault status >/dev/null 2>&1; then
    # Check if Vault is sealed
    if vault status 2>/dev/null | grep -q "Sealed.*true"; then
      echo "$(date): Vault is sealed, attempting auto-unseal..."
      
      # Get unseal key from Kubernetes secret
      UNSEAL_KEY=$(kubectl get secret vault-unseal-key -n vault -o jsonpath='{.data.unseal-key}' 2>/dev/null | base64 -d)
      if [ -n "$UNSEAL_KEY" ]; then
        echo "$(date): Retrieved unseal key, unsealing Vault..."
        if vault operator unseal "$UNSEAL_KEY" >/dev/null 2>&1; then
          echo "$(date): Vault unsealed successfully"
        else
          echo "$(date): Failed to unseal Vault"
        fi
      else
        echo "$(date): Failed to retrieve unseal key from Kubernetes secret"
      fi
    else
      echo "$(date): Vault is already unsealed"
    fi
  else
    echo "$(date): Vault is not responding yet, waiting..."
  fi
  
  # Wait before next check
  sleep 10
done