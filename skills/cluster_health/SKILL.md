---
name: cluster_health
description: Scan cluster health — Flux kustomizations, pod status, recurring crashes, node conditions, CNPG databases, certificate expiry — and output an actionable summary with fix plan. Use when user asks "how's the cluster", "cluster health", "what's broken", "check the cluster", or similar.
allowed-tools: Bash, Read, Grep, Glob, Agent
---

# Cluster Health Check

Comprehensive cluster health scan. Run all checks, collect results, then produce a single
structured report with an actionable fix plan.

## Prerequisites

`kubectl` must be configured and working. Run all `kubectl` commands outside the sandbox
(`dangerouslyDisableSandbox: true`) since they need network access.

## Check Sequence

Run these checks in parallel where possible (groups 1-4 are independent).

### Group 1: Flux GitOps Health

```bash
# All Flux kustomizations — look for False/Unknown ready status
kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,REASON:.status.conditions[?(@.type=="Ready")].reason,MSG:.status.conditions[?(@.type=="Ready")].message' \
  --sort-by='.metadata.name'

# HelmReleases
kubectl get helmreleases.helm.toolkit.fluxcd.io -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,REASON:.status.conditions[?(@.type=="Ready")].reason'

# Suspended kustomizations (expected — cross-reference with plan.md "Suspended Kustomizations")
kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A \
  -o json | python3 -c "
import json, sys
for k in json.load(sys.stdin)['items']:
    if k.get('spec', {}).get('suspend'):
        print(f\"{k['metadata']['namespace']}/{k['metadata']['name']}: suspended\")
"

# Terraform resources (tofu-controller)
kubectl get terraforms.infra.contrib.fluxcd.io -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,APPLIED:.status.conditions[?(@.type=="Apply")].status'
```

### Group 2: Pod & Workload Health

```bash
# Non-running pods (CrashLoopBackOff, ImagePullBackOff, Error, Pending, etc.)
kubectl get pods -A --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,REASON:.status.containerStatuses[0].state.waiting.reason'

# Pods with high restart counts (flapping) — threshold: >3 restarts
kubectl get pods -A -o json | python3 -c "
import json, sys
pods = json.load(sys.stdin)['items']
for p in pods:
    ns = p['metadata']['namespace']
    name = p['metadata']['name']
    for cs in p.get('status', {}).get('containerStatuses', []):
        restarts = cs.get('restartCount', 0)
        if restarts > 3:
            ready = cs.get('ready', False)
            print(f'{ns}/{name} container={cs[\"name\"]} restarts={restarts} ready={ready}')
"

# Recent pod evictions/OOMKills
kubectl get events -A --field-selector reason=OOMKilling --sort-by='.lastTimestamp' 2>/dev/null | tail -20
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp' 2>/dev/null | tail -20

# Failed jobs
kubectl get jobs -A --field-selector status.successful=0 \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,COMPLETIONS:.status.succeeded,FAILED:.status.failed'
```

### Group 3: Node Health

```bash
# Node conditions — look for NotReady, MemoryPressure, DiskPressure, PIDPressure
kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[?(@.type=="Ready")].status,MEM_PRESS:.status.conditions[?(@.type=="MemoryPressure")].status,DISK_PRESS:.status.conditions[?(@.type=="DiskPressure")].status,PID_PRESS:.status.conditions[?(@.type=="PIDPressure")].status,VERSION:.status.nodeInfo.kubeletVersion'

# Node resource usage (if metrics-server is available)
kubectl top nodes 2>/dev/null

# Longhorn node/volume health
kubectl get nodes.longhorn.io -n longhorn-system \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,SCHEDULABLE:.status.conditions[?(@.type=="Schedulable")].status' 2>/dev/null
kubectl get volumes.longhorn.io -n longhorn-system \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness' 2>/dev/null
```

### Group 4: Database & Certificate Health

```bash
# CNPG cluster health
kubectl get clusters.postgresql.cnpg.io -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,INSTANCES:.spec.instances,READY:.status.readyInstances,PHASE:.status.phase'

# Certificate expiry (cert-manager)
kubectl get certificates.cert-manager.io -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,EXPIRY:.status.notAfter,RENEWAL:.status.renewalTime'

# Challenges stuck (cert-manager)
kubectl get challenges.acme.cert-manager.io -A 2>/dev/null
```

### Group 5: Warning Events (last hour)

```bash
# Recent warning events — look for recurring patterns
kubectl get events -A --field-selector type=Warning --sort-by='.lastTimestamp' \
  -o custom-columns='NS:.metadata.namespace,OBJECT:.involvedObject.name,REASON:.reason,MSG:.message,COUNT:.count,LAST:.lastTimestamp' | tail -40
```

## Report Format

After collecting all data, produce a structured report:

```markdown
# Cluster Health Report — <date>

## Summary

<one-line overall assessment: healthy / degraded / critical>
<count of issues by severity>

## Critical Issues

<issues requiring immediate attention — broken kustomizations, CrashLoopBackOff pods,
node NotReady, CNPG clusters not healthy, expired certificates>

For each issue:

- **What**: description
- **Impact**: what's affected
- **Evidence**: kubectl output snippet
- **Fix**: specific remediation command or config change

## Warnings

<non-critical but noteworthy — high restart counts, degraded Longhorn volumes,
suspended kustomizations not in plan.md, resource pressure approaching limits>

## Expected / Known

<issues that are intentional — suspended kustomizations listed in plan.md,
scaled-to-zero deployments, maintenance windows>

## Fix Plan

<ordered list of actions to resolve critical issues and warnings,
prioritized by impact and dependency order>
```

## Cross-Reference

Check findings against known context:

- `cluster/docs/plan.md` "Suspended Kustomizations" — don't flag expected suspensions
- `cluster/docs/plan.md` "Next Actions" — note if any findings match known TODOs
- `cluster/docs/troubleshooting.md` — reference known fix procedures for matching symptoms
