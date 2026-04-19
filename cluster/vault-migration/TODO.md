# Vault Migration

Goal: eliminate Vault + ESO + the `sso-secrets` tofu-controller module by migrating:

1. **SSO client secrets** → TF-managed Authentik providers writing K8s secrets directly
   (extend the existing `sso-providers` pattern from `cluster/terraform/gitops/sso-providers/`)
2. **Non-SSO app secrets** → SOPS-encrypted K8s secrets in git

End state: Vault decommissioned, ESO removed, `sso-secrets` TF module deleted.

Existing design analysis: <../docs/plans/cluster-architecture-redesign/sso.md>

---

## Phase 1 — SSO Secrets: Extend `sso-providers` Pattern (Active Services)

For each: add `authentik_provider_oauth2` + `kubernetes_secret` resources to
`cluster/terraform/gitops/sso-providers/main.tf`, then delete the corresponding
ExternalSecret, Vault path, and blueprint `!Env` reference.

Pattern reference: Grafana/Headlamp in `sso-providers/main.tf`.

- [x] **Harbor** (`kv/sso/harbor`) — done 2026-04-18
- [x] **Matrix** (`kv/sso/matrix`, `kv/sso/oidc-providers/matrix`) — done 2026-04-18
  - Note: harbor-sso.yaml and matrix-sso.yaml blueprints set to `state: absent` (CLEANUP tombstone 2026-04-18);
    delete the files once Authentik confirms the old providers are gone.

- [ ] **Airlock** (already in `sso-providers` as `openclaw_agent` — verify complete, no Vault reference remains)
  - Check `k8s/agents/` for any remaining Vault ESO reading airlock secrets

**Skip until unsuspended**: Gitea (`kv/sso/gitea`), InvenTree (`kv/sso/inventree`).
**Vault OIDC** (`kv/sso/vault`): removed from `sso-secrets` TF and `sso-client-secrets` ESO 2026-04-18.

---

## Phase 2 — Non-SSO App Secrets: Vault → SOPS

For each: generate a SOPS-encrypted `.sops.yaml` K8s Secret, commit it, delete the
ExternalSecret and Vault path. Use `sops -e -i` from repo root so `.sops.yaml` creation
rules apply.

Active services first:

- [ ] **Matrix app secrets** (`kv/matrix/secrets`, `kv/matrix/openclaw-bot`, `kv/matrix/admin`)
  - `synapse-signing-key`, `registration-secret`, `macaroon-secret`, `redis-password`
  - openclaw-bot password (reflected to `openclaw-gateway`)
  - synapse admin credentials
  - Remove `cluster/terraform/gitops/matrix-secrets/`

- [ ] **Harbor admin** (`kv/harbor/admin`)
  - Remove `cluster/terraform/gitops/harbor-admin/`

- [ ] **Devbot credentials** (`kv/agents/devbot`) — Anthropic key, Gitea token, Harbor password, VNC password
  - These are manually maintained; just move to SOPS k8s secret
  - Update `refreshInterval` on ESO → remove ESO entirely

- [ ] **Authentik passwords** (`kv/authentik/passwords`, `kv/sso/client-secrets`)
  - `admin_password`, `secret_key`, bootstrap API token
  - Already read from k8s secret `authentik-bootstrap` by `sso-providers` TF module
  - Move to SOPS; update `k8s/authentik/secrets/` kustomization
  - Remove `cluster/terraform/gitops/authentik-passwords/` and `authentik-token/`

- [ ] **Atuin** (`kv/atuin/user`)
  - Remove `cluster/terraform/gitops/atuin-secrets/`

- [ ] **User password** (`kv/users/agentydragon`)
  - Authentik user password — move to SOPS
  - Remove `cluster/terraform/gitops/user-passwords/`

Suspended (do when unsuspending):

- [ ] **Langfuse secrets** (`kv/langfuse/secrets`) — remove when unsuspending Langfuse
- [ ] **Props secrets** (`kv/props/secrets`) — remove when unsuspending Props
- [ ] **InvenTree** (`kv/inventree/admin`, `kv/inventree/db`) — remove when unsuspending InvenTree
- [ ] **Gitea admin** (`kv/gitea/admin`) — remove when unsuspending Gitea

---

## Phase 3 — Tear Down Vault Infrastructure

Prerequisites: all ExternalSecrets deleted, `vault-backend` ClusterSecretStore has no consumers.

- [ ] Delete `cluster/k8s/external-secrets/vault-config/vault-secret-store.yaml` (ClusterSecretStore `vault-backend`)
- [ ] Delete `cluster/terraform/gitops/sso-secrets/` (entire module)
- [ ] Delete remaining empty `cluster/terraform/gitops/` secret modules (see Phase 1+2 above)
- [ ] Delete `cluster/k8s/vault/` kustomization and all manifests
- [ ] Remove Vault from `cluster/docs/bootstrap_dependencies.md`
- [ ] Remove Vault from `cluster/README.md` services table
- [ ] Delete `vault-oidc-auth` TF resource (in `sso-secrets` or wherever it lands)
- [ ] Remove ESO Vault provider from `cluster/k8s/external-secrets/` if no other secret stores remain
- [ ] Update `cluster/docs/secrets.md` to remove Vault procedures
- [ ] Clean up CLEANUP tombstones that referenced Vault

---

## Tracking

| Secret path                    | Phase | Status    |
| ------------------------------ | ----- | --------- |
| `kv/sso/harbor`                | 1     | done      |
| `kv/sso/matrix`                | 1     | done      |
| `kv/sso/gitea`                 | 1     | suspended |
| `kv/sso/inventree`             | 1     | suspended |
| `kv/sso/vault`                 | 1     | done      |
| `kv/sso/oidc-providers/matrix` | 1     | done      |
| `kv/matrix/secrets`            | 2     | todo      |
| `kv/matrix/openclaw-bot`       | 2     | todo      |
| `kv/matrix/admin`              | 2     | todo      |
| `kv/harbor/admin`              | 2     | todo      |
| `kv/agents/devbot`             | 2     | todo      |
| `kv/authentik/passwords`       | 2     | todo      |
| `kv/sso/client-secrets`        | 2     | todo      |
| `kv/atuin/user`                | 2     | todo      |
| `kv/users/agentydragon`        | 2     | todo      |
| `kv/langfuse/secrets`          | 2     | suspended |
| `kv/props/secrets`             | 2     | suspended |
| `kv/inventree/admin`           | 2     | suspended |
| `kv/inventree/db`              | 2     | suspended |
| `kv/gitea/admin`               | 2     | suspended |
