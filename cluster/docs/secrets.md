# Secrets Strategy

## TL;DR

- **SSOT**: OpenTofu state in `terraform/bootstrap/persistent-auth/terraform.tfstate` (local, gitignored)
- **Bootstrap secrets**: SealedSecrets (encrypted in git, decrypted by controller using stable keypair)
- **Runtime secrets**: External Secrets Operator reading from Vault
- **Keypair flow**: tofu state → infrastructure deploys to cluster → controller uses it

## Architecture Overview

### Three-Layer Model

**Layer 0 — Persistent Auth** (`terraform/bootstrap/persistent-auth/`)

- Sealed secrets keypair (RSA 4096, 10-year validity)
- Proxmox API tokens (CSI, OpenTofu)
- Nix cache signing key, Flux deploy key
- Storage: local `terraform.tfstate` (gitignored)
- Note: Talos machine secrets are in Layer 1 (ephemeral — fresh `cluster.id` per lifecycle)

↓

**Layer 1 — SealedSecrets** (git repo → cluster)

- `k8s/proxmox-csi/proxmox-csi-sealed.yaml`
- `k8s/applications/nix-cache/signing-key-sealed.yaml`
- `k8s/applications/nix-cache/jwt-token-sealed.yaml`
- Sealed with keypair from Layer 0, deployed by Flux, decrypted by sealed-secrets controller

↓

**Layer 2 — Vault + ESO** (runtime secrets)

- External Secrets Operator reads from Vault
- Creates K8s secrets from Vault KV paths
- Used for: application passwords, SSO credentials, etc.

## Data Flow

### Bootstrap Flow (tofu apply)

1. `persistent-auth` generates/uses keypair from tofu state
2. `persistent-auth` SSHs to Proxmox, creates API tokens
3. `persistent-auth` runs `kubeseal` to create SealedSecrets (writes to k8s/\*.yaml)
4. User commits SealedSecrets to git manually
5. `infrastructure` reads keypair via `terraform_remote_state`
6. `infrastructure` deploys keypair as `kubernetes_secret` to cluster
7. Flux deploys SealedSecrets from git
8. Controller decrypts using deployed keypair → creates regular Secrets

### Keypair Locations

| Location                                                | Purpose                |
| ------------------------------------------------------- | ---------------------- |
| `terraform/bootstrap/persistent-auth/terraform.tfstate` | SSOT (gitignored)      |
| `kube-system/sealed-secrets-key`                        | Deployed to cluster    |
| Git SealedSecrets                                       | Encrypted with keypair |

## SealedSecrets in Repository

| File                                                 | Purpose                 | Namespace   |
| ---------------------------------------------------- | ----------------------- | ----------- |
| `k8s/proxmox-csi/proxmox-csi-sealed.yaml`            | CSI driver credentials  | csi-proxmox |
| `k8s/applications/nix-cache/signing-key-sealed.yaml` | Nix cache signing       | nix-cache   |
| `k8s/applications/nix-cache/jwt-token-sealed.yaml`   | Attic JWT token         | nix-cache   |
| `k8s/dns-automation/aws-credentials-sealed.yaml`     | AWS Route 53 API access | flux-system |

## Common Failure Modes

### Keypair Mismatch

**Symptom**: `no key could decrypt secret` error on SealedSecret

**Cause**: SealedSecret in git was sealed with a different keypair than what's in tofu state

**Fix**: Re-run `tofu apply` in `bootstrap/persistent-auth` to re-seal with correct keypair

### OpenTofu State Lost

**Symptom**: New keypair generated, all SealedSecrets fail

**Prevention**:

- Backup terraform.tfstate to secure location
- Never delete persistent-auth state unless intentional full reset

## Validation

Pre-commit hook validates all SealedSecrets can be decrypted with tofu keypair:

```bash
# Validation uses kubeseal --recovery-unseal (works offline, no cluster needed)
bazel run //cluster/scripts:validate_sealed_secrets
```

## Adding New SealedSecrets

1. Create secret YAML with `kubectl create secret ... --dry-run=client -o yaml`
2. Seal with tofu keypair using the helper script (reads cert directly from tofu state):

   ```bash
   kubectl create secret generic my-secret --from-literal=key=value \
     --dry-run=client -o yaml | ./scripts/seal-secret.sh /dev/stdin k8s/path/my-sealed.yaml
   ```

3. Add to appropriate kustomization.yaml
4. Commit and push

## Keypair Verification

Compare serial numbers (should match):

```bash
# OpenTofu state:
cat terraform/bootstrap/persistent-auth/terraform.tfstate | \
  jq -r '.resources[] | select(.type == "tls_self_signed_cert") | .instances[0].attributes.cert_pem' | \
  openssl x509 -noout -serial

# Cluster:
kubectl get secret sealed-secrets-key -n kube-system -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -serial
```

## Re-sealing All Secrets

If keypair mismatch occurs:

```bash
cd terraform/bootstrap/persistent-auth && tofu apply
git add k8s/proxmox-csi/proxmox-csi-sealed.yaml
git commit -m "chore: re-seal secrets with current keypair"
git push
```
