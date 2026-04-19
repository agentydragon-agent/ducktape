# Vault Migration

Goal: eliminate Vault + ESO + the `sso-secrets` tofu-controller module.

End state: Vault decommissioned, ESO removed, `sso-secrets` TF module deleted.

Design analysis: <../docs/plans/cluster-architecture-redesign/sso.md>

---

## Phase 1 — SSO Secrets → TF+Authentik+k8s (done)

All active services migrated. Remaining suspended until unsuspended:

- [ ] **Gitea** (`kv/sso/gitea`) — suspended
- [ ] **InvenTree** (`kv/sso/inventree`) — suspended

---

## Phase 2 — Non-SSO App Secrets → SOPS

For each: generate a SOPS-encrypted `.sops.yaml` K8s Secret, delete the ExternalSecret
and Vault path. Use `sops -e -i` from repo root.

Active services:

- [ ] **Matrix app secrets** (`kv/matrix/secrets`, `kv/matrix/openclaw-bot`, `kv/matrix/admin`)
  - Covers: synapse signing key, registration secret, macaroon secret, redis password,
    openclaw-bot password (reflected to `openclaw-gateway`), synapse admin credentials
  - Remove `cluster/terraform/gitops/matrix-secrets/`

- [ ] **Authentik passwords** (`kv/authentik/passwords`, `kv/sso/client-secrets`)
  - `admin_password`, `secret_key`, bootstrap API token
  - Move to SOPS; update `k8s/authentik/secrets/` kustomization
  - Remove `cluster/terraform/gitops/authentik-passwords/` and `authentik-token/`

- [ ] **Devbot credentials** (`kv/agents/devbot`) — Anthropic key, Gitea token, Harbor password, VNC password

- [ ] **Kagent Anthropic key** (`kv/kagent`) — ESO at `k8s/agents/kagent/secrets/anthropic-secret.yaml`

- [ ] **Atuin** (`kv/atuin/user`) — remove `cluster/terraform/gitops/atuin-secrets/`

- [ ] **User password** (`kv/users/agentydragon`) — remove `cluster/terraform/gitops/user-passwords/`

Suspended (do when unsuspending):

- [ ] **Langfuse** (`kv/langfuse/secrets`)
- [ ] **Props** (`kv/props/secrets`)
- [ ] **InvenTree** (`kv/inventree/admin`, `kv/inventree/db`)
- [ ] **Gitea admin** (`kv/gitea/admin`)

---

## Phase 3 — Tear Down Vault (done 2026-04-19)

Prerequisites: all ExternalSecrets deleted, `vault-backend` ClusterSecretStore has no consumers.

- [ ] Delete `cluster/k8s/external-secrets/vault-config/vault-secret-store.yaml`
- [ ] Delete `cluster/terraform/gitops/sso-secrets/` (gitea+inventree client secrets — last entries)
- [ ] Delete remaining empty secret TF modules
- [ ] Delete `cluster/k8s/vault/` kustomization and all manifests
- [ ] Remove Vault from `cluster/docs/bootstrap_dependencies.md`
- [ ] Remove Vault from `cluster/README.md` services table
- [ ] Remove ESO Vault provider from `cluster/k8s/external-secrets/`
- [ ] Update `cluster/docs/secrets.md`
