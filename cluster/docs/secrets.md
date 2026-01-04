# Secrets Strategy

## TL;DR

- **SSOT**: Terraform state in `terraform/00-persistent-auth/terraform.tfstate` (local, gitignored)
- **Bootstrap secrets**: SealedSecrets (encrypted in git, decrypted by controller using stable keypair)
- **Runtime secrets**: External Secrets Operator reading from Vault
- **Keypair flow**: terraform state → 01-infrastructure deploys to cluster → controller uses it

## Architecture Overview

### Three-Layer Model

```text
┌─────────────────────────────────────────────────────────────┐
│ Layer 0: PERSISTENT AUTH (terraform/00-persistent-auth)    │
│ - Sealed secrets keypair (RSA 4096, 10-year validity)      │
│ - Proxmox API tokens (CSI, Terraform)                      │
│ - Nix cache signing key                                    │
│ - Flux deploy key                                          │
│ - Talos machine secrets                                    │
│ Storage: Local terraform.tfstate (gitignored)              │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: SEALED SECRETS (git repo → cluster)               │
│ - k8s/storage/proxmox-csi-sealed.yaml                      │
│ - k8s/applications/nix-cache/signing-key-sealed.yaml       │
│ - k8s/applications/nix-cache/jwt-token-sealed.yaml         │
│ Sealed with: keypair from Layer 0                          │
│ Deployed by: Flux GitOps                                   │
│ Decrypted by: sealed-secrets controller in cluster         │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: VAULT + ESO (runtime secrets)                     │
│ - External Secrets Operator reads from Vault               │
│ - Creates K8s secrets from Vault KV paths                  │
│ - Used for: application passwords, SSO credentials, etc.   │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Bootstrap Flow (terraform apply)

1. `00-persistent-auth` generates/uses keypair from terraform state
2. `00-persistent-auth` SSHs to Proxmox, creates API tokens
3. `00-persistent-auth` runs `kubeseal` to create SealedSecrets (writes to k8s/\*.yaml)
4. User commits SealedSecrets to git manually
5. `01-infrastructure` reads keypair via `terraform_remote_state`
6. `01-infrastructure` deploys keypair as `kubernetes_secret` to cluster
7. Flux deploys SealedSecrets from git
8. Controller decrypts using deployed keypair → creates regular Secrets

### Keypair Locations

| Location                                         | Purpose                |
| ------------------------------------------------ | ---------------------- |
| `terraform/00-persistent-auth/terraform.tfstate` | SSOT (gitignored)      |
| `kube-system/sealed-secrets-key`                 | Deployed to cluster    |
| Git SealedSecrets                                | Encrypted with keypair |

## SealedSecrets in Repository

| File                                                 | Purpose                | Namespace   |
| ---------------------------------------------------- | ---------------------- | ----------- |
| `k8s/storage/proxmox-csi-sealed.yaml`                | CSI driver credentials | csi-proxmox |
| `k8s/applications/nix-cache/signing-key-sealed.yaml` | Nix cache signing      | nix-cache   |
| `k8s/applications/nix-cache/jwt-token-sealed.yaml`   | Attic JWT token        | nix-cache   |

## Common Failure Modes

### Keypair Mismatch

**Symptom**: `no key could decrypt secret` error on SealedSecret

**Cause**: SealedSecret in git was sealed with a different keypair than what's in terraform state

**Fix**: Re-run `terraform apply` in `00-persistent-auth` to re-seal with correct keypair

### Terraform State Lost

**Symptom**: New keypair generated, all SealedSecrets fail

**Prevention**:

- Backup terraform.tfstate to secure location
- Never delete 00-persistent-auth state unless intentional full reset

## Validation

Pre-commit hook validates all SealedSecrets can be decrypted with terraform keypair:

```bash
# Validation uses kubeseal --recovery-unseal (works offline, no cluster needed)
./scripts/validate-sealed-secrets.sh
```

## Adding New SealedSecrets

1. Create secret YAML with `kubectl create secret ... --dry-run=client -o yaml`
2. Seal with terraform keypair using the helper script (reads cert directly from terraform state):

   ```bash
   kubectl create secret generic my-secret --from-literal=key=value \
     --dry-run=client -o yaml | ./scripts/seal-secret.sh /dev/stdin k8s/path/my-sealed.yaml
   ```

3. Add to appropriate kustomization.yaml
4. Commit and push

## Keypair Verification

Compare serial numbers (should match):

```bash
# Terraform state:
cat terraform/00-persistent-auth/terraform.tfstate | \
  jq -r '.resources[] | select(.type == "tls_self_signed_cert") | .instances[0].attributes.cert_pem' | \
  openssl x509 -noout -serial

# Cluster:
kubectl get secret sealed-secrets-key -n kube-system -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -serial
```

## Re-sealing All Secrets

If keypair mismatch occurs:

```bash
cd terraform/00-persistent-auth && terraform apply
git add k8s/storage/proxmox-csi-sealed.yaml
git commit -m "chore: re-seal secrets with current keypair"
git push
```
