# Cluster Troubleshooting Checklist

Quick diagnostic commands for common cluster issues.

## Known Issues

### Zombie Kubelet (Containerd Crash Recovery Failure)

**Symptoms**:

- Node shows Ready in `kubectl get nodes` but pods stuck in Pending
- `talosctl service kubelet status` shows: `STATE: Failed`, `HEALTH: Fail`, `service not running`
- Error: "cannot delete running task kubelet: failed precondition"
- Some pods (cilium, sealed-secrets) running but new pods cannot start
- CSI volume attachment succeeds but mount operations never happen

**Root Cause**:

- Containerd crashes (exit status 2) while kubelet is running
- Kubelet process and containerd-shim survive as orphaned processes
- Containerd restarts but loses tracking of the old kubelet container
- Talos service manager cannot delete the orphaned kubelet container to start new one

**Diagnosis**:

```bash
# Check service status
talosctl -n <node-ip> service kubelet status

# Look for zombie kubelet process
talosctl -n <node-ip> ps | grep kubelet

# Check events for failure pattern
talosctl -n <node-ip> events | grep kubelet

# Look for: "PREPARING: Creating service runner" → "FAILED: cannot delete running task"
```

**Resolution**:

1. **Reboot the affected node** (cleanest recovery):

   ```bash
   talosctl -n <node-ip> reboot
   ```

2. **Alternative** (riskier - may disrupt running pods):

   ```bash
   # Find zombie kubelet PID
   talosctl -n <node-ip> ps | grep kubelet

   # Force kill the process and shim
   talosctl -n <node-ip> kill <kubelet-pid>
   talosctl -n <node-ip> kill <shim-pid>
   ```

**Prevention**:

- **Fixed in commit 2bf6ae9**: Root cause was dual-IP assignment on workers (see below)
- Ensure workers have explicit `dhcp: false` in machine config
- Fix tf-runner crashloop to prevent container churn that triggers the issue

**Historical Occurrence**:

- 2025-11-17: worker0 - containerd crashed with exit status 2, left kubelet PID 89823 orphaned
- 2025-12-28: worker1 - same pattern, root cause identified as dual-IP + container churn

### Worker Dual-IP Assignment (DHCP + Static IP Conflict)

**Symptoms**:

- Worker nodes have two IPs on eth0 (check with `talosctl get addresses`)
- Constant "node IP skipped" messages in dmesg
- Kubelet restarts correlated with container creation/deletion
- Eventually leads to Zombie Kubelet state (see above)

**Diagnosis**:

```bash
# Check for dual IPs on workers
talosctl -n 10.2.2.1 get addresses | grep "eth0.*10\."

# Expected (good): single IP
# eth0/10.2.2.1/16

# Problem (bad): two IPs
# eth0/10.2.2.1/16
# eth0/10.0.98.85/16   ← DHCP-assigned, should not exist

# Check for NodeIPController confusion in dmesg
talosctl -n 10.2.2.1 dmesg | grep "node IP skipped"
```

**Root Cause**:

Workers were missing explicit network interface configuration:

- **Controllers**: Have `machine.network.interfaces` (for VIP) → DHCP implicitly disabled
- **Workers**: Had `network: {}` (empty) → DHCP enabled by default
- Network DHCP server assigns second IP to workers
- Talos NodeIPController sees both IPs, can't decide which is kubelet IP
- Every veth creation (container start) triggers re-evaluation
- Under sustained container churn, this destabilizes kubelet and crashes containerd

**Resolution**:

Fixed in terraform by adding explicit interface config for workers:

```yaml
machine:
  network:
    interfaces:
      - interface: eth0
        dhcp: false
```

For existing clusters, either:

1. Re-run `terraform apply` (requires cluster recreate)
2. Manually patch via talosctl:

   ```bash
   talosctl -n <worker-ip> patch machineconfig --patch \
     '[{"op": "add", "path": "/machine/network/interfaces", "value": [{"interface": "eth0", "dhcp": false}]}]'
   ```

**Prevention**:

- Commit 2bf6ae9 adds `dhcp: false` to worker machine config
- New clusters created after this fix won't have the issue

### tofu-controller TLS Secret Cache Desync (Startup GC Bug)

**Symptoms**:

- Terraform runner pods in CrashLoopBackOff with `secrets "terraform-runner.tls-XXXXXXXX" not found`
- tofu-controller logs show: `"TLS already generated for"` but secrets don't exist
- `kubectl get secret -n flux-system -l app.kubernetes.io/name=tf-runner` returns no results
- Terraform resources stuck in "Reconciliation in progress" indefinitely
- Runner pod references specific TLS secret name in args but secret is missing

**Root Cause**:

**This is a bug in tf-controller's startup garbage collection logic.** The
`garbageCollectTLSCertsForcefully()` function uses `time.Now()` as the reference
point at controller startup, causing it to delete ALL pre-existing TLS secrets
(since they were created in the past). However, the in-memory cache
(`knownNamespaceTLSMap`) is not cleared, creating a desynchronization:

1. Controller starts, `referenceTime = time.Now()` (mtls/rotator.go:164)
2. Startup GC deletes all secrets where `CreationTimestamp.Before(referenceTime)` - which is ALL of them (line 325)
3. In-memory cache still has cached `TriggerResult` entries for each namespace
4. Existing runner pods still reference the now-deleted secret names
5. New reconciliation requests hit cache and return "TLS already generated" (line 264)
6. Runner pod starts, looks for TLS secret, crashes: "secrets not found"

**Code Location**: `github.com/weaveworks/tf-controller/mtls/rotator.go`

- Bug: Line 164 sets `referenceTime = time.Now()`
- Bug: Line 180-187 calls forceful GC with this reference time at startup
- Bug: Line 325 deletes secrets created before "now" (all existing secrets)
- Cache check: Line 255 returns cached result without verifying secret exists

**Diagnosis**:

```bash
# 1. Check if TLS secrets exist
kubectl get secret -n flux-system -l app.kubernetes.io/name=tf-runner
# Should be empty if bug hit

# 2. Check runner pod logs for specific error
kubectl logs -n flux-system <terraform-name>-tf-runner
# Look for: secrets "terraform-runner.tls-XXXXXXXX" not found

# 3. Check controller logs for cache hit
kubectl logs -n flux-system deployment/tofu-controller-tf-controller --tail=100 | grep "TLS already generated"
# Controller thinks TLS is generated but it's not

# 4. Check runner pod secret reference
kubectl get pod -n flux-system <terraform-name>-tf-runner -o yaml | grep tls-secret-name
# Shows which secret the runner is looking for

# 5. Verify the secret really doesn't exist
kubectl get secret -n flux-system <secret-name-from-above>
# Should return: Error from server (NotFound)
```

**Resolution**:

**Option 1: Restart tofu-controller** (forces cache rebuild):

```bash
kubectl rollout restart deployment/tofu-controller-tf-controller -n flux-system
# Wait for controller to restart and regenerate TLS secrets
sleep 30

# Force reconcile affected Terraform resources
kubectl annotate terraform <terraform-name> -n flux-system reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
```

**Option 2: Clear cache via controller restart and force regeneration**:

```bash
# 1. Restart controller to clear in-memory cache
kubectl rollout restart deployment/tofu-controller-tf-controller -n flux-system

# 2. Wait for controller to be ready
kubectl wait --for=condition=available --timeout=60s deployment/tofu-controller-tf-controller -n flux-system

# 3. Delete all stuck runner pods to trigger fresh reconciliation
kubectl delete pods -n flux-system -l app.kubernetes.io/name=tf-runner

# 4. Controller will regenerate TLS secrets on next reconciliation
```

**Option 3: Manual cache invalidation** (if Options 1-2 don't work):

```bash
# Suspend all Terraform resources to clear runner pods
kubectl get terraform -n flux-system -o name | xargs -I {} kubectl patch {} -p '{"spec":{"suspend":true}}' --type=merge

# Delete all runner pods
kubectl delete pods -n flux-system -l app.kubernetes.io/name=tf-runner

# Restart controller to clear cache
kubectl rollout restart deployment/tofu-controller-tf-controller -n flux-system
kubectl wait --for=condition=available --timeout=60s deployment/tofu-controller-tf-controller -n flux-system

# Resume Terraform resources
kubectl get terraform -n flux-system -o name | xargs -I {} kubectl patch {} -p '{"spec":{"suspend":false}}' --type=merge
```

**Prevention**:

- This is an upstream bug in tf-controller - no cluster-side prevention available
- Monitor runner pods for CrashLoopBackOff after controller restarts
- Consider filing issue upstream: <https://github.com/weaveworks/tf-controller/issues>

**Upstream Bug Report**: TODO - file issue with tf-controller project

**Proposed Fix**: Change `referenceTime` in rotator.go:164 to use controller start
time or `time.Now().Add(-cr.CAValidityDuration)` instead of `time.Now()`, so
startup GC only deletes genuinely expired secrets, not all existing ones.

**Historical Occurrence**:

- 2025-11-19: All Terraform resources affected after investigating Kagent SSO issue
- Multiple runner pods stuck in CrashLoopBackOff for ~30 minutes
- Required controller restart to recover

### ESO Password Generator Desynchronization (SSO Authentication Failures)

**Symptoms**:

- SSO/OIDC authentication fails with "invalid client credentials" or "unauthorized"
- Authentik terraform successfully creates OIDC provider with secret A
- Kubernetes secret contains different secret B (randomly generated)
- Application uses secret B, Authentik expects secret A
- ExternalSecret using ESO Password generator instead of Vault data source

**Root Cause**:

**ESO Password generators create passwords independently on each sync, not reading from a source of truth.**
When an application's SSO configuration uses two sources for the client secret:

1. Terraform blueprint generates `random_password.result` → stores in Vault at `kv/sso/{app}` → creates Authentik provider
2. ExternalSecret uses ESO Password generator → generates different password → puts in K8s secret
3. Authentik knows password A, application uses password B → authentication fails

**Diagnosis**:

```bash
# 1. Check if ExternalSecret uses Password generator (WRONG)
kubectl get externalsecret <app>-oidc-secret -n <namespace> -o yaml | grep -A5 "generatorRef"
# If you see "kind: Password" - this is the problem

# 2. Compare passwords in Vault vs K8s secret
# Get password from Vault
kubectl exec -n vault vault-0 -c vault -- \
  env VAULT_TOKEN=<token> vault kv get -field=client_secret kv/sso/<app>

# Get password from K8s secret
kubectl get secret <app>-oauth-client-secret -n <namespace> \
  -o jsonpath='{.data.client_secret}' | base64 -d

# 3. Check terraform blueprint generates password and stores in Vault
grep -A10 "random_password.*client_secret" terraform/authentik-blueprint/<app>/main.tf
grep -A10 "vault_kv_secret_v2.*oidc" terraform/authentik-blueprint/<app>/main.tf
```

**Resolution**:

Replace ESO Password generator with Vault data source. Example fix:

```yaml
# BEFORE (WRONG - generates independent password):
---
apiVersion: generators.external-secrets.io/v1alpha1
kind: Password
metadata:
  name: app-oauth-client-secret-generator
spec:
  length: 32
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-oauth-client-secret
spec:
  dataFrom:
    - sourceRef:
        generatorRef:
          kind: Password
          name: app-oauth-client-secret-generator

# AFTER (CORRECT - reads from Vault):
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-oidc-secret
  namespace: <app>
spec:
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: app-oauth-client-secret
  data:
    - secretKey: client_id
      remoteRef:
        key: sso/<app>
        property: client_id
    - secretKey: client_secret
      remoteRef:
        key: sso/<app>
        property: client_secret
```

**Prevention**:

- ALWAYS use Vault as single source of truth for SSO credentials
- NEVER use ESO Password generator for credentials managed by terraform
- Pattern: Terraform generates → stores in Vault → ESO reads from Vault
- Review: `k8s/authentik-blueprint/*/client-secret-eso.yaml` should NOT have Password generators

**Reference Implementation**:

- Correct pattern: `k8s/applications/gitea/secrets.yaml` (lines 38-60)
- Terraform blueprint: `terraform/authentik-blueprint/gitea/main.tf`

**Historical Occurrence**:

- 2025-11-28: Harbor and Vault ExternalSecrets using Password generators
- Caused authentication failures for Harbor OIDC and vault-oidc-auth terraform
- Fixed in commit 05b5e5e by replacing generators with Vault data sources

## 🚨 Fast Path Health Checks

### Core Cluster Health

```bash
kubectl get nodes                           # All nodes should be Ready
kubectl get pods -A | grep -v Running      # Check for non-running pods
flux get kustomizations                     # Check GitOps status
```

### Storage (Proxmox CSI) - Known Tricky Component

**Common Issues**: SealedSecret decryption failures, authentication errors with misleading messages.

```bash
# 1. Check CSI pods status
kubectl get pods -n csi-proxmox

# 2. Check PVC status (if vault/storage apps are Pending)
kubectl get pvc -A
# Look for Pending PVCs

# 3. Check CSI controller logs for auth errors
kubectl logs deployment/proxmox-csi-plugin-controller -n csi-proxmox --tail=20
# Look for "401 Unauthorized" - often misleading, usually means missing token in Proxmox

# 4. Check SealedSecret health
kubectl get sealedsecret -n csi-proxmox
# STATUS should be empty (success) or show decryption error

# 5. Check if secret was created and has correct content
kubectl get secret -n csi-proxmox proxmox-csi-plugin
kubectl get secret proxmox-csi-plugin -n csi-proxmox -o jsonpath='{.data.config\.yaml}' | base64 -d

# 6. If SealedSecret shows decryption error, regenerate with stable keypair:
CSI_TOKEN_SECRET=$(secret-tool lookup service proxmox-csi key token_secret)
cat > /tmp/csi-config.yaml << EOF
clusters:
- insecure: false
  region: "cluster"
  token: "kubernetes-csi@pve!csi=$CSI_TOKEN_SECRET"
  token_id: "kubernetes-csi@pve!csi"
  token_secret: "$CSI_TOKEN_SECRET"
  url: "https://atlas.agentydragon.com/api2/json"
EOF

kubectl create secret generic proxmox-csi-plugin \
  --namespace=csi-proxmox \
  --from-file=config.yaml=/tmp/csi-config.yaml \
  --dry-run=client -o yaml | \
kubeseal --cert <(secret-tool lookup service sealed-secrets key public_key) \
  --format=yaml | kubectl apply -f -

rm /tmp/csi-config.yaml

# 7. Check if CSI token exists in Proxmox (via SSH)
ssh root@atlas "pveum token list kubernetes-csi@pve"
# Should show the csi token, if missing need to recreate via infrastructure terraform
```

### Node Issues

**Worker Node NotReady** (common: kubelet disk detection issues):

```bash
kubectl describe node <node-name>
# Look for: "InvalidDiskCapacity" errors in events
# Fix: Usually resolves on its own, or restart the node VM
```

### GitOps Issues

**Kustomization stuck/failing**:

```bash
kubectl describe kustomization <name> -n flux-system
kubectl logs deployment/kustomize-controller -n flux-system --tail=50
```

**HelmRelease stuck/failing**:

```bash
kubectl describe helmrelease <name> -n <namespace>
kubectl logs deployment/helm-controller -n flux-system --tail=50
```

## 🔧 Stable SealedSecret Keypair Issues

### Keypair Verification

```bash
# Check if stable keypair exists
secret-tool lookup service sealed-secrets key private_key >/dev/null && echo "✅ Private key exists"
secret-tool lookup service sealed-secrets key public_key >/dev/null && echo "✅ Public key exists"

# Check if cluster is using stable keypair
kubectl get secret sealed-secrets-key -n kube-system -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -text -noout | grep -A2 "Serial Number"
secret-tool lookup service sealed-secrets key public_key | openssl x509 -text -noout | grep -A2 "Serial Number"
# Serial numbers should match
```

### SealedSecret Decryption Test

```bash
# Test if a SealedSecret can be decrypted with stable keypair
kubectl get sealedsecret <name> -n <namespace> -o yaml | \
kubeseal --recovery-unseal --recovery-private-key <(secret-tool lookup service sealed-secrets key private_key)
# Should output the original secret YAML if working
```

## 🔄 Common Recovery Actions

### Restart Flux Controllers (for CRD cache issues)

```bash
kubectl rollout restart deployment/kustomize-controller -n flux-system
kubectl rollout restart deployment/helm-controller -n flux-system
```

### Force GitOps Reconciliation

```bash
kubectl annotate kustomization <name> -n flux-system fluxcd.io/reconcile="$(date +%s)" --overwrite
```

### Emergency CSI Secret Fix (storage broken)

```bash
# Delete broken SealedSecret and recreate with stable keypair
kubectl delete sealedsecret proxmox-csi-plugin -n csi-proxmox
# Then run the CSI secret regeneration from storage section above
```

## 🐛 Known Issues

### Proxmox CSI Storage

- **Issue**: SealedSecret decryption failures
- **Cause**: terraform/storage generating secrets with wrong keypair
- **Fix**: Always use stable keypair from libsecret when sealing

### Flux CRD Caching

- **Issue**: "no matches for kind" errors after CRD deployment
- **Cause**: Controller cache doesn't auto-refresh for new CRDs
- **Fix**: Restart kustomize-controller (usually resolves automatically)

### Worker Node Kubelet Issues

- **Issue**: Node stuck NotReady with "InvalidDiskCapacity"
- **Cause**: Kubelet disk detection problems
- **Fix**: Usually resolves automatically, or restart VM

### DNS & Certificate Manager

#### PowerDNS Zone Replication (AXFR)

**Architecture**:

- Primary: Cluster PowerDNS (10.2.3.3) - authoritative source
- Secondary: VPS PowerDNS (ns1.agentydragon.com) - public-facing
- Replication: AXFR over Tailscale VPN

**Check zone replication status**:

```bash
# Verify VPS has zone data
ssh root@agentydragon.com "docker exec powerdns pdnsutil list-zone test-cluster.agentydragon.com"

# Manually trigger zone transfer
ssh root@agentydragon.com "docker exec powerdns pdns_control retrieve test-cluster.agentydragon.com"

# Verify NS records are correct
dig @ns1.agentydragon.com test-cluster.agentydragon.com NS
```

**Common issues**:

- **VPS not fetching zone**: Check `secondary=yes` in VPS PowerDNS config
- **Tailscale route not working**: Verify routes advertised and enabled in Headscale
- **Old NS records cached**: Wait for TTL expiry (check with `dig test-cluster.agentydragon.com NS`)

#### cert-manager DNS-01 Validation

**Check certificate status**:

```bash
kubectl get certificates -A
kubectl get certificaterequests -A
kubectl get challenges -A
kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager --tail=50
```

**Common failures**:

1. **"propagation check failed: no such host"**
   - **Symptom**: cert-manager trying to resolve old NS record names
   - **Cause**: DNS cache still returning stale NS records
   - **Check**: `dig test-cluster.agentydragon.com NS` (check TTL)
   - **Fix**: Wait for DNS cache expiry (typically 1 hour from NS change)

2. **"webhook call failed"**
   - **Check**: PowerDNS webhook pod running: `kubectl get pods -n cert-manager -l app.kubernetes.io/name=cert-manager-webhook-powerdns`
   - **Check**: PowerDNS API accessible:
     `kubectl exec -n cert-manager deployment/cert-manager-webhook-powerdns -- wget -O-
     http://powerdns-api.dns-system:8081/api/v1/servers`

3. **Challenge TXT record not created**
   - **Check**: PowerDNS logs: `kubectl logs -n dns-system deployment/powerdns`
   - **Check**: Webhook logs: `kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager-webhook-powerdns`
   - **Verify**: API key secret exists: `kubectl get secret powerdns-api-key -n cert-manager`

**Force certificate retry**:

```bash
# Delete failed resources to trigger fresh attempt
kubectl delete challenge -n <namespace> --all
kubectl delete order -n <namespace> --all
kubectl delete certificaterequest -n <namespace> --all
# Certificate resource will recreate them automatically
```

### Nix Cache Issues

#### Pod Not Starting

```bash
kubectl get pods -n nix-cache
kubectl describe pod -n nix-cache -l app=harmonia
kubectl logs -n nix-cache deployment/harmonia
```

**Common issues:**

- **PVC not bound**: Check Proxmox CSI status: `kubectl get pods -n csi-proxmox`
- **SealedSecret not unsealed**: Check controller: `kubectl get secret nix-cache-signing-key -n nix-cache`
- **Image pull failure**: Verify image name in deployment.yaml

#### Storage Issues

```bash
kubectl get pvc -n nix-cache
kubectl exec -n nix-cache deployment/harmonia -- df -h /nix/store
```

**Full storage**: If PVC is full, either:

1. Expand PVC: `kubectl edit pvc nix-store -n nix-cache` (increase size)
2. Implement garbage collection (see plan.md Future Enhancements)

#### Signing Key Issues

```bash
# Check secret exists
kubectl get secret nix-cache-signing-key -n nix-cache

# Verify key in libsecret
secret-tool lookup service nix-cache key signing_public

# Get public key for NixOS config
secret-tool lookup service nix-cache key signing_public | head -1
# Output: cache.test-cluster.agentydragon.com-1:BASE64KEY
```

**If signing key missing**: Re-run terraform in `terraform/00-persistent-auth`

#### Upload Failures from NixOS Host

```bash
# On NixOS host, test upload
nix copy --to https://cache.test-cluster.agentydragon.com /nix/store/xxx-hello-xxx --debug

# Check Harmonia logs
kubectl logs -n nix-cache deployment/harmonia --tail=100
```

**Common causes:**

1. **Storage full**: Check PVC usage above
2. **Signing key mismatch**: Verify Harmonia loaded correct key
3. **Network issues**: Check ingress and certificate

#### HTTPS Access Not Working

```bash
# Check ingress
kubectl get ingress -n nix-cache
kubectl describe ingress harmonia -n nix-cache

# Check certificate
kubectl get certificate -n nix-cache
kubectl describe certificate nix-cache-tls -n nix-cache

# Test from inside cluster
kubectl run -it --rm debug --image=curlimages/curl:latest --restart=Never -- \
  curl http://harmonia.nix-cache.svc.cluster.local:5000/nix-cache-info
```

**Expected response**:

```text
StoreDir: /nix/store
WantMassQuery: 1
Priority: 30
```
