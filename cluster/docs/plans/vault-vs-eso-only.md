# Vault vs ESO-Only: What Would We Lose?

**Date**: 2026-03-20
**Status**: Analysis

## Current Architecture

```text
Terraform (tofu-controller)
  → generates random_password
  → writes vault_kv_secret_v2 to Vault KV v2
  → ~15 modules under terraform/gitops/

Vault (Bank-Vaults operator, 3-replica Raft HA)
  → single KV v2 mount at "kv"
  → stores ~50 secret paths (SSO, app creds, API keys, user passwords)

ESO (ClusterSecretStore: vault-backend)
  → ~40+ ExternalSecrets across all namespaces
  → polls Vault every 24h
  → creates K8s Secrets for pods
```

## What Vault Buys Us

### 1. Cross-Namespace Secret Coordination (primary value)

One Terraform module generates a secret, writes it to one Vault path, and multiple
ExternalSecrets in different namespaces read from it.

**Example — SSO client secrets**:

- `sso-secrets/` TF generates 10 OAuth2 client secrets → writes to `kv/sso/{app}`
- ESO in `authentik` namespace reads `kv/sso/harbor` → Authentik worker knows the secret
- ESO in `harbor` namespace reads `kv/sso/harbor` → Harbor OIDC config uses same secret
- Both get the same value, zero manual coordination

**Example — Langfuse API keys**:

- `langfuse-secrets/` TF writes to `kv/langfuse/secrets`
- ESO in `langfuse` namespace reads `project_public_key`, `postgres_password`, etc.
- ESO in `ollama` namespace reads `project_public_key`, `project_secret_key` for LiteLLM

### 2. Terraform → K8s Bridge

Terraform writes to Vault using the `hashicorp/vault` provider (one provider, one auth
token). Without Vault, each TF module would need `kubernetes` provider config + RBAC to
write secrets into potentially many target namespaces. Vault is a single write target
that ESO fans out from.

### 3. KV v2 Versioning

Vault KV v2 stores version history. Used for rollback when TF state goes sideways (e.g.,
`vault kv rollback -version=1` to fix the Authentik token 403 — see
<troubleshooting.md#authentik-api-token-403-vault-version-desync>).

### 4. Check-and-Set (`cas`)

`cas = 0` on `vault_kv_secret_v2` resources prevents silent overwrites when TF state is
lost and re-created. Without this, a fresh `tofu apply` would silently overwrite
production secrets.

### 5. Vault OIDC Auth / UI

`vault-oidc-auth/` TF module configures Vault's own OIDC backend so users can log into
the Vault UI at `vault.allegedly.works` via Authentik SSO. Low value — rarely used.

## The ESO-Only Alternative

Replace Vault with a **"secrets namespace"** pattern:

1. Create a `secrets` namespace (or reuse `flux-system`)
2. Terraform writes K8s Secrets there via `kubernetes_secret` resources
3. ESO `kubernetes` ClusterSecretStore points at the secrets namespace
4. All ExternalSecrets switch `secretStoreRef` from `vault-backend` to the new store

This is already partially proven — `external-secrets-config.yaml` already defines
`kubernetes` ClusterSecretStores for `authentik`, `headscale`, and
`openclaw-gateway` namespaces. The mechanism works.

### What We'd Keep

- Cross-namespace secret sharing (via ESO kubernetes provider)
- Terraform-generated secrets as SSOT
- ExternalSecret declarations (just change `secretStoreRef`)
- Stakater Reloader (pod restarts on secret changes)

### What We'd Lose

| Capability                     | Impact                                                                                                                                                                |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| KV v2 versioning/rollback      | **Medium** — no `vault kv rollback` when TF overwrites. Mitigation: TF state is the SSOT anyway; K8s secret history could be approximated by etcd snapshots or Velero |
| Check-and-set (`cas`)          | **Low** — TF `lifecycle { ignore_changes }` already prevents most overwrites; K8s `kubernetes_secret` can use `create`-only with ignore on update                     |
| Vault UI for secret browsing   | **Low** — `kubectl get secret -o yaml` or Headlamp                                                                                                                    |
| Vault OIDC auth                | **None** — remove, not needed                                                                                                                                         |
| Audit log (Vault audit device) | **Low** — not currently enabled anyway                                                                                                                                |

### What We'd Gain

| Benefit                              | Impact                                                                                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Eliminate 3-replica Vault HA cluster | **High** — 3 pods, 3x10Gi PVCs, Bank-Vaults operator, vault-token bootstrap chain                                                                                   |
| Simpler bootstrap dependency graph   | **High** — Vault is a prerequisite for ESO → prerequisite for ~everything. Removing it shortens the bootstrap critical path                                         |
| No more root-token-in-K8s-secret     | **Medium** — the `instance-unseal-keys` secret with root token is a security concern (any pod in vault namespace can read it, ESO ClusterSecretStore references it) |
| Fewer moving parts to debug          | **Medium** — eliminates vault-operator, vault-token, vault-oidc-auth, vault-ingress, vault-servicemonitor kustomizations                                            |
| Secrets visible with plain kubectl   | **Low** — already true (ESO creates K8s Secrets), but removes one layer of indirection when debugging                                                               |

## Migration Scope

### Terraform Changes (~15 modules)

Every `terraform/gitops/*/main.tf` that uses `vault_kv_secret_v2` would change to
`kubernetes_secret` (or `kubernetes_secret_v1`). The `vault` provider block and
`vault_address`/`vault_token` variables would be removed. A `kubernetes` provider
block would replace them (tofu-controller already has K8s RBAC in `flux-system`).

For cross-namespace writes, either:

- Write all secrets to the `secrets` namespace (needs one new RBAC binding)
- Write to each target namespace (needs per-namespace RBAC — more complex)

### ExternalSecret Changes (~40+ files)

Change `secretStoreRef.name` from `vault-backend` to the new kubernetes
ClusterSecretStore. Update `remoteRef.key` from `kv/service/path` to
`{secret-name}` and `remoteRef.property` to the K8s secret data key.

Or: if TF writes directly to the target namespace, many ExternalSecrets become
unnecessary — pods can mount the TF-created secret directly. This would be a
larger refactor but further simplifies the architecture.

### Kustomizations to Delete

- `vault/` (instance)
- `vault-operator/` (Bank-Vaults Helm chart)
- `vault-token/` (root token bootstrap)
- `vault-oidc-auth/` (OIDC config)
- `vault-ingress/` (HTTPRoute)
- `vault-servicemonitor/` (Prometheus scraping)

### Kustomizations to Modify

- `external-secrets/` — remove `vault-backend` ClusterSecretStore, add/expand kubernetes store

## Recommendation

Vault is **overweight for the job it does here**. It's used exclusively as a KV store —
no dynamic secrets, no PKI, no transit encryption, no lease management. The only Vault
feature that adds real value beyond what K8s Secrets provide is KV v2 versioning, which
has been needed exactly once (Authentik token rollback).

The migration is moderate effort (~55 files to touch) but would meaningfully simplify
the cluster's dependency graph, bootstrap sequence, and operational burden. The "secrets
namespace + ESO kubernetes provider" pattern is already proven in this cluster.

**If migrating**: do it incrementally — move one TF module at a time, starting with a
simple one (e.g., `ollama-api-key`), validate the pattern, then batch-migrate the rest.
