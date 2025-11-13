# Harbor OIDC Helm Configuration - Archived

This directory contains the original Helm-based Harbor OIDC configuration files that have been replaced by Terraform automation.

## Migration Date
November 8, 2025

## Reason for Migration
The Helm-based approach suffered from timing and synchronization issues:
- External Secrets Operator (ESO) refresh delays (5 minutes)
- Race conditions between Harbor config job and Authentik blueprint processing  
- Complex dependency management across multiple Helm charts
- "invalid_client" errors due to secret mismatches

## Files Archived

### Helm Templates/Jobs
- `harbor-oidc-config-job.yaml` - Harbor OIDC configuration Kubernetes Job
- `harbor-oidc-external-secret.yaml` - ESO secret for Harbor (duplicate)
- `authentik-harbor-oauth-external-secret.yaml` - ESO secret for Authentik
- `harbor-oidc-secret-generator.yaml` - Vault secret generator Job
- `harbor.yaml` - Authentik blueprint template
- `harbor-setup/` - Entire Harbor setup Helm chart

### Values Files (Backed Up)
- `harbor-values-original.yaml` - Original Harbor Helm values
- `authentik-values-original.yaml` - Original Authentik values  
- `authentik-blueprints-values-original.yaml` - Original blueprint values

## Current Solution
Harbor OIDC configuration is now managed by:
- **Location**: `tf/applications/`
- **Benefits**: 
  - ✅ No timing issues - Terraform ensures proper dependency ordering
  - ✅ Single secret source - Generated once, used by both systems
  - ✅ Vault integration - Root-level Vault access for full automation
  - ✅ Auto-generated credentials - No manual token/password creation
  - ✅ Atomic updates - Both systems change together or rollback

## What Was Removed From Active Configuration

### Harbor Values (`k8s/helmfile/values/harbor.yaml`)
```yaml
# REMOVED:
existingSecretAdminPassword: "harbor-oidc-secret" 
authMode: "oidc_auth"
oidc:
  name: "Authentik"
  endpoint: "https://auth.k3s.agentydragon.com/application/o/harbor/"
  # ... entire oidc block
```

### Authentik Values (`k8s/helm/authentik/values-authentik.yaml`)  
```yaml
# REMOVED:
configMaps:
  - authentik-blueprints-harbor  # Commented out

env:
  - name: HARBOR_CLIENT_SECRET  # Commented out
```

### Blueprint Values (`k8s/helm/authentik/values-blueprints.yaml`)
```yaml  
# REMOVED:
harbor:
  externalHost: "https://registry.k3s.agentydragon.com"
  adminGroup: "harbor-admins"
  useExternalSecret: true
```

## DO NOT USE THESE FILES
These files are archived for reference only. Using them will:
- ❌ Create conflicts with Terraform-managed resources
- ❌ Reintroduce timing/synchronization issues
- ❌ Cause "invalid_client" OIDC errors

## Reverting (If Needed)
To revert to Helm-based configuration:
1. Destroy Terraform resources: `terraform destroy` in `tf/applications/`
2. Restore original values files from this archive
3. Move Helm templates back to their original locations
4. Re-enable ESO secrets and Harbor config job

**Note**: This is NOT recommended due to the synchronization issues that led to this migration.