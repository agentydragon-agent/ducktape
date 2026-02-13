# Talos Cluster Operations

Operational procedures for day-to-day cluster management, scaling, maintenance, and troubleshooting.

## Essential Operations

```bash
# Force reconciliation
flux reconcile helmrelease sealed-secrets

# Check PowerDNS
kubectl get pods -n dns-system
kubectl get svc powerdns-external -n dns-system

# Create sealed secret
kubectl create secret generic my-secret --from-literal=key=value --dry-run=client -o yaml | \
  kubeseal -o yaml > my-sealed-secret.yaml

# Fetch certificate (verify controller access)
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

```bash
# From Kubernetes perspective
kubectl delete node talos-controlplane0

# Update terraform.tfvars to reduce count, then:
terraform apply
```

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

## Troubleshooting Common Issues

### Bootstrap Hanging

**Symptoms**: `talosctl bootstrap` times out or hangs
**Solution**: Verify cluster_endpoint points to first controller IP, not VIP:

```hcl
cluster_endpoint = "https://10.2.1.1:6443"  # NOT 10.2.3.1:6443
```

### Static IP Not Working

**Symptoms**: VMs get DHCP addresses instead of static IPs
**Solution**: Check META key 10 configuration in module and restart VMs

### API Not Responding

**Symptoms**: `connection refused` on port 50000
**Solution**: Wait longer for boot, check console via screenshots

### Network Connectivity Issues

**Symptoms**: Cannot reach VMs on expected IPs
**Solution**: Verify network configuration in terraform.tfvars matches infrastructure

### Switching Let's Encrypt Environment (Staging ↔ Production)

The cluster uses kustomize overlays to switch between Let's Encrypt staging and production environments.

**Current configuration**: Check `k8s/cert-manager-environment/flux-kustomization.yaml`

```yaml
spec:
  path: "./k8s/cert-manager-environment/overlays/staging"     # staging (fake certs, high rate limits)
  # OR
  path: "./k8s/cert-manager-environment/overlays/production"  # production (real certs, strict rate limits)
```

**To switch environments**:

1. Edit the path in `k8s/cert-manager-environment/flux-kustomization.yaml`
1. Commit and push the change
1. Wait for Flux to reconcile, or force it:

```bash
flux reconcile source git flux-system
flux reconcile kustomization cert-manager-environment
```

1. Delete existing certificates to trigger re-issuance with new issuer:

```bash
kubectl delete certificates --all -A
# Certificates will be automatically recreated by cert-manager
```

**Environment differences**:

| Environment    | ACME Server                          | Rate Limits       | Certificate Trust     |
| -------------- | ------------------------------------ | ----------------- | --------------------- |
| **Staging**    | acme-staging-v02.api.letsencrypt.org | 30,000 certs/week | Untrusted (test only) |
| **Production** | acme-v02.api.letsencrypt.org         | 50 certs/week     | Browser-trusted       |

**When to use each**:

- **Staging**: Development, testing certificate issuance, debugging DNS-01 challenges
- **Production**: When ready for real browser-trusted certificates

### Let's Encrypt DNS Challenge Fails

**Symptoms**: `REFUSED` responses during certificate creation
**Root Causes & Solutions**:

1. **Missing DNS Delegation** (Most Common):
   - **Symptom**: "No TXT record found at \_acme-challenge.domain.com"
   - **Solution**: Add NS delegation record in parent domain DNS (AWS Route 53)
   - **Fix**: `domain.com` → NS → `ns1.agentydragon.com`

2. **PowerDNS TSIG Permission Missing**:
   - **Symptom**: DNS updates rejected with "REFUSED"
   - **Solution**: Add TSIG metadata to zone
   - **Fix**: `pdnsutil set-meta domain.com TSIG-ALLOW-DNSUPDATE certbot`

3. **PowerDNS DNS Update Access Denied**:
   - **Symptom**: "Remote not listed in allow-dnsupdate-from"
   - **Solution**: Add VPS IP to PowerDNS allow list
   - **Fix**: Update `powerdns_allow_dnsupdate_from` in Ansible

### NodePort Services Not Accessible Externally

**Symptoms**: 502 Bad Gateway or connection refused to NodePorts
**Root Causes & Solutions**:

1. **Cilium kube-proxy Replacement Disabled**:
   - **Symptom**: NodePorts not listening on node interfaces
   - **Solution**: Enable in Cilium configuration
   - **Fix**: `kubeProxyReplacement: "true"`

2. **NodePort Bind Protection Enabled**:
   - **Symptom**: NodePorts only accessible from localhost
   - **Solution**: Disable bind protection in Cilium
   - **Fix**: `nodePort.bindProtection: false`

3. **Wrong Node for NodePort Access**:
   - **Symptom**: Connection refused to specific node
   - **Solution**: Use worker nodes where ingress pods run
   - **Fix**: Target w0/w1 instead of c0/c1/c2 (controllers)

### Nodes Become NotReady

**Symptoms**: `kubectl get nodes` shows nodes as "NotReady", pods stuck in Pending
**Root Cause**: Kubelet services stuck waiting for volumes to mount (after restarts/updates)
**Solution**: Restart kubelet services using talosctl

```bash
# Restart kubelet on affected node
talosctl -n <node-ip> service kubelet restart

# Verify nodes return to Ready status
kubectl get nodes
```

### NGINX Ingress Controller in CrashLoopBackOff

**Symptoms**: NGINX controller pods failing to start, "no service found" errors
**Root Causes & Solutions**:

1. **Missing NodePort Service**:
   - **Symptom**: "no service with name ingress-nginx-controller found"
   - **Solution**: Ensure HelmRelease creates proper NodePort service
   - **Fix**: Wait for Flux reconciliation or force with `flux reconcile`

2. **DaemonSet Port Conflicts** (Architecture Issue):
   - **Symptom**: Multiple pods trying to bind same hostNetwork ports
   - **Solution**: Use Deployment instead of DaemonSet
   - **Fix**: Configure `kind: Deployment` with pod anti-affinity

3. **Duplicate HelmReleases**:
   - **Symptom**: Conflicting configurations causing resource conflicts
   - **Solution**: Remove duplicate configurations
   - **Fix**: Keep only one ingress configuration, clean up old namespaces

### tofu-controller Terraform Resources Stuck Reconciling

**Symptoms**: Terraform resources show "Reconciliation in progress" for hours, tf-runner pods stuck in
Terminating state

**Root Cause**: tofu-controller doesn't fail-fast on provider authentication errors (e.g., expired Authentik
API tokens). Instead of marking resources as Failed, it retries indefinitely with "Reconciliation in progress"
status.

**Impact**: Provider auth failures (403, invalid credentials) appear as normal reconciliation, blocking
dependent resources via dependency chains without clear error indication.

**Diagnosis**:

```bash
# Check Terraform resource status
kubectl get terraform -n flux-system

# Check tf-runner pod logs for auth errors
kubectl logs -n flux-system -l tf.contrib.fluxcd.io/run-id=<run-id> --tail=100

# Look for "403 Token invalid/expired" or similar auth errors
```

**Solution**:

```bash
# 1. Fix the underlying authentication issue (regenerate tokens, update secrets)

# 2. Remove finalizers from stuck Terraform resources
kubectl patch terraform <name> -n flux-system -p '{"metadata":{"finalizers":[]}}' --type=merge

# 3. Force delete stuck tf-runner pods
kubectl delete pod -n flux-system <pod-name> --force --grace-period=0

# 4. Reconcile kustomizations to recreate with fresh credentials
flux reconcile kustomization <name> --with-source
```

**Prevention**:

- Monitor Terraform resource age: resources "Reconciling" > 10 minutes likely stuck
- Check tf-runner pod logs periodically for auth errors
- Consider implementing automated alerts on long-running Terraform reconciliations

**Future Improvement**: tofu-controller should distinguish between retryable transient errors and terminal
authentication failures. Consider filing upstream issue if this becomes frequent operational burden.

### Flux Controllers Not Starting

**Symptoms**: Flux pods stuck in ContainerCreating, GitOps not working
**Root Cause**: Worker nodes NotReady prevents pod scheduling
**Solution**: Fix underlying node issues first, then Flux recovers automatically

### PowerDNS DNS Issues

**Architecture**: PowerDNS runs directly in the Kubernetes cluster on VPS nodes with `hostNetwork: true`.
No AXFR replication or secondary DNS server. Nameservers are `ns1.allegedly.works` and `ns2.allegedly.works`.

**Symptoms**: DNS queries fail, cert-manager DNS-01 challenges fail
**Root Causes & Solutions**:

1. **PowerDNS Pods Not Running**:
   - **Check**: `kubectl get pods -n dns-system -l app.kubernetes.io/name=powerdns`
   - **Solution**: Check pod logs and events

2. **PowerDNS API Not Accessible**:
   - **Symptom**: cert-manager fails to create DNS-01 challenge records
   - **Solution**: Check PowerDNS pod logs and API service
   - **Fix**: Verify PowerDNS API key secret exists in cert-manager namespace (reflector copies from dns-system)

## Reference Information

### Node Assignments (3-node Hybrid Cluster)

**Hetzner VPS Nodes** (dynamic IPs assigned by Hetzner):

| Node           | Server Type | Location      | Role                       |
| -------------- | ----------- | ------------- | -------------------------- |
| talos-vps-cp-0 | CPX31       | Hillsboro, OR | Controlplane (schedulable) |
| talos-vps-cp-1 | CPX31       | Hillsboro, OR | Controlplane (schedulable) |

**Proxmox Home Nodes** (static IPs):

| Node           | VM ID | IP Address | Role         |
| -------------- | ----- | ---------- | ------------ |
| talos-pve-cp-0 | 10000 | 10.2.1.1   | Controlplane |

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
