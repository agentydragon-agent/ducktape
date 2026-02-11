# Bootstrap Investigation: 2026-02-11

## Overview

Comprehensive analysis of two issues encountered during cluster bootstrap on 2026-02-11:

1. Transient cross-node DNS resolution failure
2. Kyverno webhook validation timeouts on HelmRelease installation

Both issues are now fully root-caused with actionable fixes.

## Documents

### observations.md

Complete technical investigation (**677 lines, 27 KB**) including:

- Executive summary
- Detailed timeline (Phase 1-4)
- Root cause analysis for both issues
- Technical deep dives:
  - Cilium IPAM mode "kubernetes" behavior
  - VXLAN + KubeSpan interaction
  - Kyverno webhook readiness sequence
  - KubeSpan peer status details
- Current cluster state summary
- Proposed fixes with code examples
- Verification procedures
- Lessons learned

**Read this for**: Complete understanding of what happened, why, and how to prevent it

### SUMMARY.txt

Quick reference summary (**30 lines, 3.2 KB**):

- Executive summary of both issues
- Current cluster state
- Key technical insights
- Files that need editing
- Required actions
- Verification checklist

**Read this for**: Quick overview and action items

---

## Quick Links

### Issue 1: Transient DNS Resolution Failure

- **Location in observations.md**: "Issue 1: Transient DNS Resolution Failure (Cross-Node Networking)"
- **Root Cause**: Cilium VXLAN tunnel map incompletely initialized
- **Status**: Self-resolved after ~5-10 minutes
- **Action Required**: None (documentation in troubleshooting guide recommended)

### Issue 2: Kyverno Webhook Timeout

- **Location in observations.md**: "Issue 2: Kyverno Webhook Timeout on HelmRelease Installation"
- **Root Cause**: Missing `dependsOn: kyverno` declarations
- **Status**: Ready for fix
- **Action Required**: YES - edit 2 kustomization files
  - `k8s/cert-manager-trust/flux-kustomization.yaml`
  - `k8s/ingress-nginx/flux-kustomization.yaml`

---

## Key Findings

### Technical Details

| Aspect              | Finding                                                                   |
| ------------------- | ------------------------------------------------------------------------- |
| Pod CIDR Allocation | Kubernetes mode: 10.244.0.0/24 - 10.244.4.0/24 across 4 nodes             |
| Tunnel Protocol     | VXLAN (UDP 4789) - required for hybrid VPS + Proxmox                      |
| Mesh Protocol       | KubeSpan (Talos WireGuard, UDP 51820) - bridges public + private networks |
| Convergence Time    | 5-15 minutes from bootstrap start to full stability                       |
| Webhook Readiness   | ~10-20 seconds from pod Running to VWC operational                        |

### Root Causes

**DNS Issue**:

- VXLAN tunnel endpoints registered after pod CIDRs advertised
- Timing race during initial pod network setup
- Self-resolved once all nodes Ready (signal that CNI converged)

**Webhook Issue**:

- Kyverno VWC not created until webhook controller runs (inside pod)
- HelmReleases in cert-manager-trust and ingress-nginx attempted deployment before VWC Ready
- Missing explicit `dependsOn: kyverno` in flux-kustomization.yaml

### Cluster State

```text
Post-Resolution Status:
✅ All 4 nodes Ready
✅ All kustomizations Ready (100+)
✅ All core services operational
✅ DNS working end-to-end
✅ KubeSpan mesh converged
✅ Cilium tunnel map stable
```

---

## Implementation Checklist

- [ ] Review observations.md for complete context
- [ ] Edit cert-manager-trust flux-kustomization.yaml (add `dependsOn: kyverno`)
- [ ] Edit ingress-nginx flux-kustomization.yaml (add `dependsOn: kyverno`)
- [ ] Test changes on next bootstrap cycle
- [ ] Verify no webhook timeout errors in HelmRelease status
- [ ] Update AGENTS.md with Kyverno dependency pattern (optional)
- [ ] Update docs/troubleshooting.md with bootstrap timing section (optional)

---

## Related Documentation

- **AGENTS.md**: Flux Kustomization Layering (CRD Dependencies)
- **CLAUDE.md**: Critical Flux Reconciliation workflow
- **docs/troubleshooting.md**: Fast Path Health Checks (should add bootstrap section)
- **README.md**: General cluster architecture and network layout

---

## Contact / Questions

For detailed technical questions, refer to specific sections in observations.md:

- Cross-node networking: See "Cilium VXLAN Tunnel Map (Post-Convergence)" section
- Webhook readiness: See "Kyverno ValidatingWebhookConfiguration Readiness" timeline
- IPAM behavior: See "Technical Deep Dives" → "Cilium IPAM Mode: Kubernetes"
