# Talos Cluster Operations

Operational procedures for day-to-day cluster management, scaling, maintenance, and troubleshooting.

## Sealed Secrets

```bash
# Create sealed secret (uses direnv-provided kubeseal)
kubectl create secret generic my-secret --from-literal=key=value --dry-run=client -o yaml | \
  kubeseal -o yaml > my-sealed-secret.yaml

# Verify controller can provide its cert
kubeseal --fetch-cert
```

## Node Operations

### Adding New Nodes

### Controller Node

```bash
cd /home/agentydragon/code/ducktape/cluster/terraform/bootstrap/infrastructure

# Add new node to the `proxmox_nodes` or `hetzner_nodes` locals map
# Apply changes
terraform apply

# New nodes will automatically join the cluster
# Verify with talosctl get members
```

### Node Maintenance

### Restart Single Node

```bash
# Gracefully restart a node (example: controlplane0)
talosctl \
  --endpoints 10.2.1.1 \
  --nodes 10.2.1.1 \
  reboot

# Or force restart via Proxmox
ssh root@atlas 'qm reboot 10000'
```

### Remove Node

Remove the node from `proxmox_nodes` or `hetzner_nodes` locals in terraform, then `terraform apply`.
Kubernetes node object will be cleaned up automatically.

## System Diagnostics

### VM Console Management

### Take VM Screenshots

See `~/.claude/skills/proxmox_vm/vm-screenshot.sh`

### Direct VM Console Access

```bash
# Interactive console access (from Proxmox host)
ssh root@atlas
qm terminal 10000  # talos-pve-cp-0
```

## Switching Let's Encrypt Environment (Staging ↔ Production)

A single ConfigMap controls which Let's Encrypt issuer is active cluster-wide:

```yaml
# k8s/cert-manager-issuer-config/configmap.yaml
data:
  LETSENCRYPT_ISSUER: letsencrypt-prod # or letsencrypt-staging
```

Both ClusterIssuers (`letsencrypt-prod`, `letsencrypt-staging`) are always deployed.
The ConfigMap selects which one is used via Flux `postBuild.substituteFrom`.

**How switching works:**

Every Ingress has `cert-manager.io/cluster-issuer: "${LETSENCRYPT_ISSUER}"` annotation,
substituted by Flux from the ConfigMap. When the toggle flips:

1. Flux re-renders all Ingresses with the new annotation value
2. cert-manager detects annotation change, updates each Certificate's `issuerRef`
3. cert-manager re-issues all certificates from the new issuer
4. Trust bundle switches automatically (`${LETSENCRYPT_ISSUER}-root-ca`)

**To switch:**

1. Edit `LETSENCRYPT_ISSUER` in `k8s/cert-manager-issuer-config/configmap.yaml`
2. Commit and push
3. Wait for Flux to reconcile (or force: `flux reconcile source git flux-system`)

No manual certificate deletion needed — cert-manager handles re-issuance automatically.

**Environment differences**:

| Environment    | ACME Server                          | Rate Limits       | Certificate Trust     |
| -------------- | ------------------------------------ | ----------------- | --------------------- |
| **Staging**    | acme-staging-v02.api.letsencrypt.org | 30,000 certs/week | Untrusted (test only) |
| **Production** | acme-v02.api.letsencrypt.org         | 50 certs/week     | Browser-trusted       |

**When to use each**:

- **Staging**: Development, testing certificate issuance, debugging DNS-01 challenges
- **Production**: When ready for real browser-trusted certificates

## Troubleshooting

See <troubleshooting.md> for diagnostic commands and known issues.

## Security Configuration

### Privileged Ports (Port < 1024)

Services that need to bind to privileged ports (e.g., DNS on port 53) require the `NET_BIND_SERVICE` capability when
running as non-root user to comply with Pod Security Standards "restricted" policy.

**Example Configuration**:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 953
  runAsGroup: 953
  allowPrivilegeEscalation: false
  capabilities:
    add: ["NET_BIND_SERVICE"] # Required for ports < 1024
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
```

**Common Services Requiring This**:

- DNS servers (port 53): PowerDNS, CoreDNS, Unbound
- HTTP servers (port 80): Only when not using LoadBalancer/Ingress
- HTTPS servers (port 443): Only when not using LoadBalancer/Ingress

**Troubleshooting**:

- **Symptom**: Pod stuck in `Init:0/1` or container won't start
- **Check**: `kubectl describe pod <pod-name>` for permission errors
- **Solution**: Add `NET_BIND_SERVICE` capability to container securityContext
