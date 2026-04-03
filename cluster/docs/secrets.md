# Secrets Strategy

## TL;DR

- **Bootstrap secrets**: SOPS-encrypted in git (`*.sops.yaml`), decrypted by Flux
- **Runtime secrets**: Vault → External Secrets Operator → K8s Secrets
- **Encryption keys**: Age keypairs in `.sops.yaml` (admin + cluster keys)
- **Full dependency graph**: <bootstrap-dependencies.md>

## Architecture

### Two-Layer Model

**Layer 1 — SOPS Secrets** (git → Flux → cluster)

Secrets are age-encrypted YAML files committed to git. Flux decrypts them
using the cluster age key (`sops-age-cluster-secrets` in `flux-system`).

Files in `cluster/k8s/**/*.sops.yaml` (26 files) contain app credentials,
API keys, and infrastructure tokens. Files in `secrets/*.yaml` contain
infrastructure secrets (Nebula CA, Flux deploy key, cluster age keypair).

**Layer 2 — Vault + ESO** (runtime secrets)

External Secrets Operator reads from Vault KV and creates K8s Secrets.
Used for: SSO client secrets, database passwords, application credentials.
Terraform generates passwords → stores in Vault → ESO syncs to K8s.

## Age Keys

Defined in `.sops.yaml` creation rules:

| Key                              | Purpose                                       | Storage                                                                                 |
| -------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------- |
| Admin age key (`age1u858...`)    | Decrypt all secrets locally                   | Derived from `~/.ssh/id_ed25519` via ssh-to-age                                         |
| Cluster age key (`age1nywe...`)  | Flux decrypts `k8s/**/*.sops.yaml` in-cluster | `secrets/cluster-secrets-age.yaml` → deployed to `flux-system/sops-age-cluster-secrets` |
| Host keys (wyrm2, rugged, atlas) | Per-host sops-nix secrets                     | Derived from host SSH keys                                                              |

## Adding New SOPS Secrets

```bash
# Create a new SOPS-encrypted secret
sops cluster/k8s/<app>/secrets/my-secret.sops.yaml
```

SOPS uses `.sops.yaml` creation rules to determine which age keys encrypt the
file based on its path. Commit and push — Flux deploys automatically.

## Rotating Credentials

1. Get new credential from external service
2. `sops cluster/k8s/<path>.sops.yaml` — edit the value
3. Commit + push; Flux deploys; Stakater Reloader restarts affected pods

## Rotating the Cluster Age Key

1. Generate: `age-keygen -o /dev/stdout`
2. Update `secrets/cluster-secrets-age.yaml` with new keypair
3. Update `.sops.yaml` with new public key
4. Re-encrypt all cluster secrets: `for f in $(find cluster/k8s -name '*.sops.yaml'); do sops updatekeys "$f"; done`
5. `tofu apply` to deploy new k8s secret
6. Commit + push

## Common Failure Modes

### SOPS Decryption Failure in Flux

**Symptom**: Kustomization shows `sops decryption error`

**Cause**: Cluster age key in `flux-system/sops-age-cluster-secrets` doesn't
match the key used to encrypt the file.

**Fix**: Verify the key matches `.sops.yaml`, re-encrypt if needed with
`sops updatekeys`, redeploy the k8s secret via `tofu apply`.

### OpenTofu State Lost

**Symptom**: SOPS age secret not deployed to cluster; Flux can't decrypt

**Prevention**:

- PG backend with backup CronJob (`pg_dump` every 6 hours)
- Age keypair also stored in `secrets/cluster-secrets-age.yaml` (SOPS-encrypted
  with admin key) — survives tofu state loss

## Validation

Pre-commit validates SOPS files can be decrypted:

```bash
bazel run //devinfra/precommit
```
