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

| Key                              | Purpose                                       | Storage                                                                                        |
| -------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Admin age key (`age1u858...`)    | Decrypt all secrets locally                   | Derived from `~/.ssh/id_ed25519` via ssh-to-age                                                |
| Cluster age key (`age1nywe...`)  | Flux decrypts `k8s/**/*.sops.yaml` in-cluster | `secrets/shared/cluster-secrets-age.yaml` → deployed to `flux-system/sops-age-cluster-secrets` |
| Host keys (wyrm2, rugged, atlas) | Per-host sops-nix secrets                     | Derived from host SSH keys                                                                     |

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
2. Update `secrets/shared/cluster-secrets-age.yaml` with new keypair
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
- Age keypair also stored in `secrets/shared/cluster-secrets-age.yaml` (SOPS-encrypted
  with admin key) — survives tofu state loss

## Proxmox CSI Token

The Proxmox CSI driver authenticates to the Proxmox API using an API token
for the `kubernetes-csi@pve` user. The token is stored in a SOPS-encrypted
secret at `k8s/proxmox-csi/secrets/proxmox-csi.sops.yaml`.

### Provisioning (after bootstrap or token rotation)

1. **Verify the token exists** on Proxmox:

   ```bash
   ssh root@atlas.nebula.allegedly.works \
     "pveum user token list kubernetes-csi@pve --output-format json"
   ```

   The token `csi` should exist. If not, tofu creates it via `persistent-auth.tf`.

2. **Get the token secret** from Proxmox:

   ```bash
   ssh root@atlas.nebula.allegedly.works \
     "grep kubernetes-csi /etc/pve/priv/token.cfg"
   # Output: kubernetes-csi@pve!csi <token-secret-uuid>
   ```

3. **Update the SOPS secret**:

   ```bash
   cd /path/to/ducktape  # must be repo root for .sops.yaml rules
   sops cluster/k8s/proxmox-csi/secrets/proxmox-csi.sops.yaml
   ```

   Set the values in `stringData.config.yaml`:

   ```yaml
   clusters:
     - url: https://10.2.0.2:8006/api2/json
       insecure: true
       token_id: kubernetes-csi@pve!csi
       token_secret: <token-secret-uuid>
       region: proxmox
   ```

4. **Commit and push** — Flux deploys the secret, CSI driver picks it up.

### Verifying

```bash
kubectl get secret proxmox-csi-plugin -n csi-proxmox
kubectl logs deployment/proxmox-csi-plugin-controller -n csi-proxmox
```

## Nebula Certs for Non-Talos Nodes

Talos nodes get nebula certs generated by tofu and embedded in machine config
(see `persistent-auth.tf` `local.talos_nebula_nodes`). Non-Talos nodes (wyrm2,
rugged, iguana, atlas, activitywatch, k8s-worker-test) have certs in
`secrets/nebula/` — plaintext `.crt` files + SOPS binary `.sops.key` files.

```text
secrets/nebula/
  ca.crt              # plaintext PEM — CA public cert (shared)
  ca.sops.key         # SOPS binary — CA private key (admin only)
  wyrm2.crt           # plaintext PEM — host public cert
  wyrm2.sops.key      # SOPS binary — host private key (admin + host)
  ...
```

Certs are inspectable without decryption: `nebula-cert print -path secrets/nebula/wyrm2.crt`

### Generating a new cert

```bash
# Decrypt CA key (requires admin age key)
TMPCA=$(mktemp -d)
sops -d secrets/nebula/ca.sops.key > "$TMPCA/ca.key"

# Sign — FQDN must be {host}.nebula.allegedly.works, IP from the cert being rotated
# (or pick a free 10.42.0.x/16 for new nodes)
nebula-cert sign \
  -ca-crt secrets/nebula/ca.crt \
  -ca-key "$TMPCA/ca.key" \
  -name "HOST.nebula.allegedly.works" \
  -ip "IP/16" \
  -out-crt secrets/nebula/HOST.crt \
  -out-key "$TMPCA/host.key"

# Encrypt the private key as SOPS binary
cp "$TMPCA/host.key" secrets/nebula/HOST.sops.key
sops -e -i secrets/nebula/HOST.sops.key

# Clean up
rm -rf "$TMPCA"
```

### Deploying

- **NixOS workers** (wyrm2, rugged, iguana): `nixos-rebuild switch` — certs
  deployed via `environment.etc`, key via sops-nix binary format
  (`nix/nixos/modules/k8s-worker-sops.nix`)
- **atlas**: `ansible-playbook atlas.yaml --tags nebula` — certs copied from
  plaintext files, key decrypted from SOPS binary
- **k8s pods** (activitywatch): Flux deploys from `*.sops.yaml` in `k8s/`

### After cert rotation

1. Commit the new `.crt` and `.sops.key` files
2. Deploy (nixos-rebuild, ansible, or push for Flux)
3. Restart nebula: `sudo systemctl restart nebula`

## Validation

Pre-commit validates SOPS files can be decrypted:

```bash
bazel run //devinfra/precommit
```
