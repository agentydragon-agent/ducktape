# Application Configuration with Terraform

This Terraform configuration manages the OIDC integration between Harbor and Authentik, solving the synchronization issues that occur with the Helm-only approach.

## Prerequisites

1. **K3s cluster running** with Harbor and Authentik deployed via Helm
2. **Root Vault access**: Full Vault permissions to create/manage secrets
3. **Cluster admin access**: Root-level access to create Kubernetes resources
4. **Environment setup**: Set `VAULT_TOKEN` or configure other Vault auth

## Setup (Fully Automated!)

1. **Set up Vault authentication**:
   ```bash
   export VAULT_TOKEN="your_vault_token"
   # Or configure other Vault auth method
   ```

2. **Initialize and apply**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

That's it! No manual token creation needed - everything is automated.

## What This Does

### Problem Solved
- **Timing Issues**: Eliminates race conditions between Harbor config job and Authentik blueprint processing
- **Secret Synchronization**: Ensures both systems use the exact same client secret
- **Atomic Updates**: Changes both systems together or not at all

### Resources Created
1. **Vault secrets** (`kv/harbor`) with admin password and client secret
2. **Authentik API token** (auto-generated via Kubernetes)
3. **Authentik OAuth2 Provider** with Harbor configuration
4. **Authentik Application** for Harbor
5. **Harbor OIDC configuration** with proper dependencies
6. **Kubernetes secret** (optional, for debugging)

### Benefits Over Helm Approach
- ✅ **No timing issues**: Authentik configured before Harbor
- ✅ **Vault-managed secrets**: Single source of truth for all secrets
- ✅ **Auto-generated credentials**: No manual token/password creation
- ✅ **Explicit dependencies**: Terraform ensures correct order
- ✅ **Rollback capability**: Can revert both systems atomically
- ✅ **GitOps ready**: Store in Git, apply via CI/CD

## Usage

### Initial Setup
```bash
# After Harbor + Authentik are deployed via Helm:
terraform apply
```

### Secret Rotation  
```bash
# Force recreation of client secret:
terraform apply -replace=module.harbor_authentik_oidc.random_password.harbor_client_secret
```

### Debugging
```bash
# Check current configuration:
terraform show

# View generated secret (sensitive):
terraform output -raw harbor_client_secret
```

## Integration with Existing Workflow

This complements your existing Helm deployments:

1. **Infrastructure**: K3s cluster (existing Terraform)
2. **Applications**: Harbor + Authentik pods (Helm charts)  
3. **Configuration**: OIDC relationship (this Terraform)

The OIDC configuration can be updated independently of application deployments.

## Removing Helm OIDC Configuration

After this is working, you can remove from your Helm setup:

1. **Harbor**: Remove `harbor-oidc-config-job`
2. **Authentik**: Remove blueprint OIDC configuration
3. **ESO**: Remove `harbor-oidc-external-secret` (or keep for other purposes)

This eliminates the complex synchronization logic while keeping the apps deployed via Helm.