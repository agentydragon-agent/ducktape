# Vault Helm Chart

Wrapper chart that installs HashiCorp Vault (HA Raft) with sensible defaults for
the Ducktape cluster and exposes a `ClusterSecretStore` for External Secrets.

## Features

- Three-node HA cluster using integrated Raft storage.
- TLS via cert-manager (expect `vault-tls` secret to exist).
- Bootstrap hook that enables the KV secret engine and Kubernetes auth method.
- Optional integration with External Secrets Operator.
- Declarative OIDC configuration via Authentik (enable in `values.yaml`).

## Usage

```bash
cd k8s/helm/vault
helm dependency update
helm upgrade --install vault . \
  --namespace vault --create-namespace
```

### Prerequisites

- cert-manager with the `homelab-ca-issuer` (or whichever issuer you configure)
  available; the chart auto-creates a `Certificate` and corresponding secret.
- `external-secrets.io` installed if you want the `ClusterSecretStore`.

### Post-Install

1. Unseal the cluster (if auto-unseal not configured):
   ```bash
   kubectl exec -n vault statefulset/vault -c vault -- vault operator init
   kubectl exec -n vault pod/vault-0 -c vault -- vault operator unseal <key>
   ```
2. Log in and create policies/roles (see docs below). If you prefer auto-unseal,
   configure the seal stanza and mount the necessary credentials in values.

If `.Values.oidc.enabled` is set and the required secrets exist, a post-install
job configures the OIDC auth method using the Authentik blueprint (which
publishes client credentials via the `vault-oidc-credentials` secret).

### OIDC Secrets

Create two Kubernetes secrets before installing with OIDC enabled:

1. `vault-oidc-credentials` – contains `client-id` and `client-secret` issued by
   Authentik (the blueprint reads the same values via environment variables).
2. `vault-root-token` – contains an administrative token (or a limited token
   with `sudo` capability on `auth/oidc/*`) used by the config job.
3. The chart installs a service account (`vault-controller`) with read access to
   secrets in the namespace so the job can consume these credentials.

If you manage secrets via SealedSecrets, set the ciphertext in
`values.yaml` under `secrets.rootToken.token`. The chart will render a
SealedSecret for `vault-root-token`. The OIDC client credentials are managed by
the Authentik chart’s blueprint; populate
`authentik.values.yaml: secrets.vaultOIDCCredentials` with the sealed data and
reflector will copy the secret into the Vault namespace automatically.

For production deployments consider enabling auto-unseal via a cloud KMS so the
cluster restarts without manual intervention.

## Operations

- **Rotate Raft snapshots:** `vault operator raft snapshot save ...`
- **Create CI robot secrets:**
  ```bash
  vault kv put kv/registry/ci-robot password=<plaintext> htpasswd=<bcrypt>
  ```
- **Grant External Secrets access:** bind a Kubernetes auth role named
  `external-secrets` to the desired service account.

### External Secrets Example

After deployment you can reference Vault secrets in other namespaces:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: registry-ci-robot
  namespace: registry
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault
    kind: ClusterSecretStore
  target:
    name: registry-ci-robot
  data:
    - secretKey: htpasswd
      remoteRef:
        key: registry/ci-robot
        property: htpasswd
```
