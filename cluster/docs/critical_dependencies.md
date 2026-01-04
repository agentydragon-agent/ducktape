# Critical Dependencies and Bootstrap Order

## Dependency Chain

The hybrid cluster has a strict dependency chain:

```text
1. Talos OS (base system on all 4 nodes)
   ↓
2. KubeSpan (WireGuard mesh between VPS ↔ home)
   ↓
3. Kubernetes API Server
   ↓
4. CNI (Cilium with VXLAN tunnel mode)
   ↓
5. Sealed Secrets Controller
   ↓
6. CSI Drivers (Hetzner CSI for VPS, Proxmox CSI for home)
   ↓
7. Application workloads
```

## Critical Services

1. **KubeSpan**: WireGuard mesh connecting VPS and home nodes
2. **CNI (Cilium)**: Pod networking with VXLAN for cross-node communication
3. **Sealed Secrets**: Required for CSI authentication secrets
4. **CSI Drivers**: Hetzner CSI (VPS storage), Proxmox CSI (home storage)

## Bootstrap Order

### Layer 0: Persistent Auth (run once)

- Talos machine secrets
- Proxmox API tokens
- Sealed secrets keypair

### Layer 1: Infrastructure

1. Hetzner VPS nodes created (2x CPX31)
2. Proxmox VMs created (1x controlplane, 1x worker)
3. Cluster bootstrapped from first VPS
4. KubeSpan mesh established
5. Cilium CNI installed
6. Sealed secrets keypair deployed

### Layer 2: Services (GitOps)

1. Sealed secrets controller
2. CSI drivers (Hetzner, Proxmox)
3. Platform services (Vault, Authentik, Harbor)

## Known Issues and Recovery

### KubeSpan Mesh Connectivity

**Symptom**: Nodes can't communicate across VPS ↔ home boundary

**Check**: `talosctl get kubespanpeerstatuses` - state should be "up"

**Recovery**: Verify UDP 51820 open on all nodes, check discovery service reachability

### CSI Driver Issues

**Hetzner CSI** (VPS nodes):

- Check: `kubectl get pods -n kube-system -l app=hcloud-csi`
- Requires: `HCLOUD_TOKEN` in cluster

**Proxmox CSI** (home nodes):

- Check: `kubectl get pods -n csi-proxmox`
- Requires: Valid Proxmox API token (from 00-persistent-auth)

### Sealed Secrets Keypair

**Current Approach**: Terraform generates stable keypair in 00-persistent-auth layer

**Key Points**:

- Keypair persists across cluster destroy/recreate
- All SealedSecrets in git must match current keypair
- Use `./scripts/seal-secret.sh` for new secrets

## Engineering Best Practices

1. **Never disrupt critical services on a running cluster**
2. **Test changes via destroy/recreate cycle**
3. **Document circular dependencies and break with proper sequencing**
4. **Keep persistent auth layer separate from cluster lifecycle**
