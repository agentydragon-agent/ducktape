# RWO Volume Deployment Strategy Issue

**TL;DR:** If your application uses ReadWriteOnce (RWO) persistent volumes with a single replica, you MUST use
`strategy.type: Recreate` instead of the default `RollingUpdate`. Otherwise, you'll get deadlocks when pods fail
during initialization.

## The Problem

When a Kubernetes Deployment with `RollingUpdate` strategy uses RWO volumes, a deadlock can occur:

```text
Old Pod (Init:Error)  ←───┐
      ↓                    │
  Volume attached          │  Can't terminate until
      ↓                    │  new pod is Ready
  Won't release volume     │
      ↓                    │
New Pod (Pending)          │
      ↓                    │
  Needs volume             │
      ↓                    │
  Multi-Attach error ──────┘  Can't become Ready
                               without volume
```

### Why This Happens

1. **RollingUpdate behavior**: Tries to start the new pod BEFORE terminating the old one
2. **RWO constraint**: Volume can only be attached to ONE node at a time
3. **Init:Error pods don't release volumes**: A pod in `Init:Error` is still "Running" from kubelet's perspective -
   it's just restarting the init container
4. **Deployment controller waits**: Won't terminate old pod until new pod is Ready
5. **New pod can't start**: Can't attach the volume because old pod still has it
6. **Deadlock**: Neither pod can make progress

### Real-World Example

```yaml
# Gitea pod stuck in Init:Error (configure-gitea fails with TLS error)
gitea-76b5b5c759-sn59s   0/1     Init:Error   24 (26s ago)   14m

# New pod created during rolling update
gitea-7c5cd987fd-jlhpp   0/1     Init:0/3     0              3s

# Event on new pod:
Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-f4816c2d-97ba-474f-b66c-a0d88732203f"
         Volume is already used by pod(s) gitea-76b5b5c759-sn59s
```

The old pod's init container is failing (e.g., TLS certificate verification), so it keeps restarting. The Deployment
controller creates a new pod with updated config, but it can't get the volume. **Manual intervention required** to
break the deadlock.

## The Solution

For single-replica deployments with RWO volumes, use `Recreate` strategy:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-stateful-app
spec:
  replicas: 1
  strategy:
    type: Recreate  # ← CRITICAL for RWO volumes
  template:
    spec:
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: my-app-data  # RWO volume
```

### Recreate Strategy Behavior

1. Deployment controller terminates the old pod
2. Waits for old pod to fully terminate and release volume
3. Creates new pod
4. New pod attaches volume and starts successfully

**Downside**: Brief downtime during updates (old pod stops before new pod starts). But this is acceptable for
single-replica stateful apps, and it's better than deadlocks requiring manual intervention.

## When to Use Each Strategy

### Use `Recreate` when

- ✅ Single replica (`replicas: 1`)
- ✅ Using RWO (ReadWriteOnce) persistent volumes
- ✅ Application is stateful (database, Git server, file storage, etc.)
- ✅ Brief downtime during updates is acceptable

**Examples**: Gitea, Harbor registry, PostgreSQL, MariaDB, single-instance apps with persistent data

### Use `RollingUpdate` when

- ✅ Multiple replicas (`replicas: > 1`)
- ✅ No persistent volumes, OR using RWX (ReadWriteMany) volumes
- ✅ Application is stateless or can handle concurrent versions
- ✅ Zero-downtime updates are required

**Examples**: Web frontends, API servers, stateless microservices

### Can't Use Either If

- ❌ Single replica + RWO volume + need zero-downtime updates
  - **Solution**: Rearchitect for HA (multiple replicas + RWX volumes or external storage)

## Helm Chart Configuration

Most Helm charts expose `strategy` as a top-level value:

```yaml
# values.yaml or HelmRelease spec.values
strategy:
  type: Recreate

# Some charts nest it under deployment:
deployment:
  strategy:
    type: Recreate
```

Check the chart's `values.yaml` to find the correct path.

## Auditing Existing Deployments

Run this to find deployments that might be affected:

```bash
# Find single-replica deployments using RollingUpdate with PVCs
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do
  kubectl get deployment -n $ns -o json | jq -r '
    .items[] |
    select(.spec.replicas == 1 and .spec.strategy.type == "RollingUpdate") |
    select(.spec.template.spec.volumes[]?.persistentVolumeClaim != null) |
    "\(.metadata.namespace)/\(.metadata.name)"
  '
done
```

For each result, check if the PVC uses `accessModes: [ReadWriteOnce]`:

```bash
kubectl get pvc -n <namespace> -o yaml | grep -A1 accessModes
```

If it's RWO, add `strategy.type: Recreate` to the deployment/HelmRelease.

## Historical Occurrences in This Cluster

This issue has affected us **multiple times**:

1. **Occurrence 1**: [Add details]
2. **Occurrence 2**: [Add details]
3. **Occurrence 3**: Gitea (2025-12-10) - Init container TLS verification failure caused 14-minute deadlock
   requiring manual ReplicaSet scaling

Each time required manual intervention (deleting old pods or scaling down old ReplicaSets) to break the deadlock.

## Recommended Action Items

- [ ] Audit all single-replica deployments with RWO volumes (see script above)
- [ ] Add `strategy.type: Recreate` to affected deployments
- [ ] Document this pattern in deployment templates/guidelines
- [ ] Consider this during cluster architecture reviews

## References

- Kubernetes Issue: [#61156](https://github.com/kubernetes/kubernetes/issues/61156) - RollingUpdate deadlock with RWO volumes
- Kubernetes Documentation: [Deployment Strategies](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#strategy)
- This cluster's experience: `docs/troubleshooting.md` - Zombie Kubelet section shows related volume attachment issues

## See Also

- `docs/troubleshooting.md` - Known Issues section
- `docs/operations.md` - Deployment best practices
- `k8s/applications/gitea/helmrelease.yaml` - Reference implementation with Recreate strategy
