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
tofu apply

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

Remove the node from `proxmox_nodes` or `hetzner_nodes` locals in OpenTofu, then `tofu apply`.
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

See <bootstrap.md> for the issuer toggle mechanism. To switch:

1. Edit `LETSENCRYPT_ISSUER` in `k8s/cert-manager-issuer-config/configmap.yaml`
2. Commit and push
3. Flux re-renders all Ingresses and cert-manager re-issues certificates automatically

**Rate limit warning:** Each switch re-issues all certificates. Avoid rapid toggling
(5 duplicate certs/domain/week on production LE).

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
