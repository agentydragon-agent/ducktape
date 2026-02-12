# Investigation: Kyverno Webhook Timeout During Bootstrap

**Date**: 2026-02-11
**Status**: Root cause identified, fix applied (pending verification on next bootstrap)

## Summary

Three HelmReleases (cert-manager-trust, tofu-controller, ingress-nginx) permanently
failed during bootstrap because the Kyverno validating webhook timed out on cross-node
TLS handshakes. Combined with the default `install.remediation.retries: 0` (no retries),
a single transient network failure blocked the entire dependency chain (49 kustomizations).

## Timeline (UTC)

| Time      | Event                                                                                |
| --------- | ------------------------------------------------------------------------------------ |
| 21:31:34  | helm-controller starts                                                               |
| 21:32:06  | Kyverno HelmRelease install starts                                                   |
| 21:32:16  | Kyverno pods created on `talos-pve-worker-0` (10.244.3.x)                            |
| 21:32:47  | Kyverno admission-controller main container starts                                   |
| 21:32:53  | Startup probe fails: `TLS handshake error: secret "...-tls-pair" not found`          |
| 21:32:54  | Kyverno registers `ValidatingWebhookConfiguration` (failurePolicy: Fail)             |
| 21:32:59  | **Kyverno pod becomes Ready** (startup + readiness probes pass)                      |
| 21:33:01  | Kyverno HelmRelease install succeeds                                                 |
| 21:33:18  | `require-gitops` ClusterPolicy loaded                                                |
| 21:35:34  | trust-manager + tofu-controller install actions start (5m timeout)                   |
| 21:35:47  | **Kyverno log: `TLS handshake error from 10.244.0.75:51260: EOF`**                   |
| 21:35:48  | **Kyverno log: `TLS handshake error from 10.244.0.75:51268: EOF`**                   |
| 21:35:49  | tofu-controller FAILS after 15s (one webhook timeout = 10s + overhead)               |
| 21:35:58  | trust-manager FAILS after 24s                                                        |
| 21:36:08  | ingress-nginx FAILS after 20s; **Kyverno log: TLS handshake error from 10.244.0.75** |
| 21:36:08+ | All 3 in terminal `RetriesExceeded` state — no further retry                         |

## Root Cause: Two Contributing Factors

### Factor 1: Cross-Node TLS Handshake Failure (Transient)

The kube-apiserver on `talos-vps-cp-1` (pod CIDR `10.244.0.0/24`) could not complete
TLS handshakes with the Kyverno webhook on `talos-pve-worker-0` (pod CIDR `10.244.3.0/24`).

**Evidence**: Kyverno logs show `TLS handshake error from 10.244.0.75: EOF` at exactly
the times the Helm installs failed. The source IP is in VPS-CP-1's pod CIDR range.

The kube-apiserver (hostNetwork) calls the webhook through Cilium's service routing
(ClusterIP 10.98.201.238 → pod 10.244.3.87). This traffic traverses:

- Cilium VXLAN tunnel (pod-to-pod overlay)
- KubeSpan WireGuard mesh (VPS ↔ Proxmox connectivity)

At ~3 minutes post-bootstrap, this cross-node path was apparently not yet stable.

**Proof it's transient**: A curl test 10 minutes later completes successfully in 88ms:

```text
HTTP 200 connect=0.085s tls=0.089s total=0.089s
```

### Factor 2: HelmRelease Default Retry Count = 0 (Permanent)

All three failed HelmReleases use the Flux default `install.remediation.retries: 0`,
meaning **a single failed install attempt is terminal**. The HelmRelease enters
`RetriesExceeded` state and never retries unless manually force-reconciled.

**Impact**: A single 10-second webhook timeout permanently blocks 49 downstream
kustomizations through the dependency chain:

```text
cert-manager-trust (FAILED) → cert-manager-environment → ...
core/tofu-controller (FAILED) → storage → vault → external-secrets → ALL apps
ingress-nginx (FAILED) → gitea, harbor, matrix, headscale, website
```

## Webhook Configuration

The `validate.kyverno.svc-fail` ValidatingWebhookConfiguration:

- **failurePolicy: Fail** — webhook unavailability blocks API calls
- **timeoutSeconds: 10** — max wait per webhook call
- **scope**: apps/v1 `deployments`, `daemonsets`, `statefulsets` (CREATE, UPDATE)
- **namespaceSelector**: excludes `kube-system` and `kyverno` only

This explains why `sealed-secrets`, `metrics-server`, and `reloader` (all in `kube-system`)
installed successfully — they're excluded from the webhook.

## Why This Didn't Happen to Kyverno Itself

Kyverno's own HelmRelease installed at 21:32:06, **before** the webhook was registered
at 21:32:54. At install time, there was no validating webhook to call.

## Node Topology at Time of Failure

| Component                             | Node               | Pod CIDR   | IP           |
| ------------------------------------- | ------------------ | ---------- | ------------ |
| helm-controller                       | talos-pve-worker-0 | 10.244.3.x | 10.244.3.133 |
| kyverno-admission-controller          | talos-pve-worker-0 | 10.244.3.x | 10.244.3.87  |
| kube-apiserver (processing admission) | talos-vps-cp-1     | 10.244.0.x | 5.78.106.249 |

**Key**: helm-controller and kyverno are on the SAME node, but the webhook call goes
through the kube-apiserver (on a DIFFERENT node), which then calls back to kyverno.
The cross-node hop is: API server (VPS) → KubeSpan → Cilium VXLAN → Kyverno (Proxmox).

## Fix

### Immediate: Force-reconcile failed releases

```bash
for hr in flux-system/tofu-controller cert-manager-trust/trust-manager ingress-system/ingress-nginx; do
  ns=$(echo $hr | cut -d/ -f1)
  name=$(echo $hr | cut -d/ -f2)
  kubectl annotate helmrelease $name -n $ns reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
done
```

### Declarative: Add install retries to all HelmReleases

**Status**: ✅ APPLIED. All 27 HelmReleases now have `install.remediation.retries: 3`.

Set `install.remediation.retries: 3` on every HelmRelease so transient webhook timeouts
during bootstrap don't cause permanent failure. With 3 retries and the default
`retryInterval: 10s`, Helm will retry for ~40 seconds before giving up — enough time
for cross-node networking to stabilize.

### Declarative: Kyverno HA on control plane nodes

**Status**: ✅ APPLIED. Admission controller now runs 3 replicas on control plane nodes.

Kyverno admission controller configured with:

- `replicas: 3` (one per control plane node)
- `nodeSelector: node-role.kubernetes.io/control-plane`
- `tolerations` for control plane NoSchedule taint
- `topologySpreadConstraints` for hard one-per-node spreading

This ensures every API server has a local Kyverno pod to call, eliminating
the cross-node hop that caused TLS handshake failures during bootstrap.

## Lessons

1. **Kyverno with failurePolicy: Fail is a bootstrap hazard** — it registers webhooks
   before cross-node networking is guaranteed stable
2. **Flux default retries=0 is too aggressive for bootstrap scenarios** — any transient
   failure becomes permanent
3. **Cross-node networking through KubeSpan+VXLAN needs ~3-5 minutes to fully stabilize**
   after bootstrap; services deployed in this window are at risk
