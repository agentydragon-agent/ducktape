# Critical Dependencies and Bootstrap Order

## Dependency Chain

The cluster has a strict dependency chain that must be respected during bootstrap and operations:

```text
1. Talos OS (base system)
   ↓
2. Kubernetes API Server
   ↓
3. CNI (Cilium) - Network connectivity
   ↓
4. Sealed Secrets Controller
   ↓
5. CSI Driver (Proxmox CSI)
   ↓
6. Application workloads
```

## Critical Services That Must Not Be Disrupted

1. **CNI (Cilium)**: Without network, nothing works
2. **Sealed Secrets**: Required for CSI authentication
3. **CSI Driver**: May manage critical volumes (though kubelet volumes are local in our setup)

## Known Issues and Recovery

### Worker Node Kubelet Volume Mount Issue

**Symptom**: Worker nodes show as NotReady with kubelet waiting for `/var/lib/kubelet` volume

**Cause**: Talos sometimes fails to properly mount kubelet volumes on boot

**Recovery**:

1. Soft reboot: `talosctl reboot -n <node-ip>`
2. Hard reset if needed: `ssh root@atlas qm reset <vm-id>`

### Sealed Secrets Keypair Management

**Current Approach**: Terraform generates a stable TLS keypair that persists in terraform state

**Key Points**:

- Keypair is deployed before Flux starts
- All secrets must be resealed when keypair changes
- Use `jsonencode()` for CSI config to avoid YAML quoting issues

## Bootstrap Order

1. **Infrastructure Layer** (terraform/infrastructure):
   - Creates VMs
   - Bootstraps Talos
   - Installs CNI (Cilium)
   - Deploys sealed-secrets keypair
   - Bootstraps Flux

2. **GitOps Layer** (Flux):
   - Installs sealed-secrets controller
   - Deploys CSI driver
   - Manages application workloads

## Engineering Best Practices

1. **Never disrupt critical services on a running cluster**
   - Plan changes carefully
   - Consider dependency impacts
   - Test in destroy/recreate cycles

2. **Always verify dependencies before making changes**
   - Check what depends on the service you're modifying
   - Understand the full impact chain

3. **Document all circular dependencies**
   - Identify them early
   - Break cycles with proper bootstrap sequencing

4. **Use proper engineering process**:
   - Map dependencies first
   - Plan the approach
   - Execute systematically
   - Verify each step
   - Document lessons learned

## Terraform Sealed Secrets Automation

The sealed-secrets-sealer.tf automatically:

1. Generates secrets in correct format
2. Seals them with terraform-managed keypair
3. Writes them to k8s/ directory
4. Can auto-commit if configured

This ensures secrets are always correctly sealed for the current keypair.
