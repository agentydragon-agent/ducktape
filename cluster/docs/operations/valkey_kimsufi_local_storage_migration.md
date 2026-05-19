# Valkey Kimsufi Local-Storage Migration

Status: draft, being paved on `manifold-mcp/manifold-valkey`.
Last live inventory refresh: 2026-05-19.

This note covers two related tasks:

- deciding what blocks decommissioning `talos-vps-worker-0` and
  `talos-vps-worker-1`;
- moving operator-managed Valkey state to Kimsufi local storage through Flux.

## Current VPS Worker PVCs

These PVCs are currently mounted by pods on the two VPS workers. PV names are
included because local-path PVs are bound to a specific node and host path.

### `talos-vps-worker-0`

| PV                                         | PVC                                                         | Pod                      | Purpose                                                                      | Notes                                                                                                                                              |
| ------------------------------------------ | ----------------------------------------------------------- | ------------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pvc-08d96ead-94e1-4610-a109-d91074d1c67b` | `grocy-sf/grocy-sf-valkey-grocy-sf-valkey-1`                | `grocy-sf-valkey-1`      | Grocy SF MCP OAuth/session state Valkey replica                              | Master is already `grocy-sf-valkey-0` on `talos-kimsufi-worker-0`; this is a removable old-site replica after replacement/scale-down cleanup.      |
| `pvc-df39ef94-2de0-4946-9410-4187e57da00c` | `grocy-vallejo/grocy-vallejo-valkey-grocy-vallejo-valkey-1` | `grocy-vallejo-valkey-1` | Grocy Vallejo MCP OAuth/session state Valkey replica                         | Master is already `grocy-vallejo-valkey-0` on `talos-kimsufi-worker-0`; this is a removable old-site replica after replacement/scale-down cleanup. |
| `pvc-b12db62a-efee-41c9-b158-70a30f766cdd` | `loki/storage-loki-0`                                       | `loki-0`                 | Loki single-binary local WAL/cache; chunks and indexes use SeaweedFS S3      | Helm values pin singleBinary persistence to `local-path-hetzner` and region `hil`. Needs a Loki-specific migration or accepted cache/WAL loss.     |
| `pvc-54c804b4-e1c5-4122-956d-7f65236e5305` | `manifold-mcp/manifold-valkey-manifold-valkey-0`            | `manifold-valkey-0`      | Manifold MCP OAuth/session state Valkey master                               | This is the first Valkey migration target. The only replica is `manifold-valkey-1` on `talos-kimsufi-worker-0`.                                    |
| `pvc-87eb5e5d-f588-4b20-870d-946c6da4022b` | `monitoring/storage-mimir-compactor-0`                      | `mimir-compactor-0`      | Mimir compactor local working state/cache; long-term blocks use SeaweedFS S3 | StatefulSet with one replica and `local-path-hetzner`. Needs monitoring Helm value migration.                                                      |
| `pvc-1e35cc4f-913d-4d75-99e3-4af241eba2b1` | `monitoring/storage-mimir-ingester-0`                       | `mimir-ingester-0`       | Mimir ingester local TSDB/WAL                                                | StatefulSet with one replica and `local-path-hetzner`; this is the riskiest monitoring PVC because it can contain recent samples before upload.    |
| `pvc-e8d15fd7-de1d-4887-94ab-4123c77a2785` | `monitoring/storage-mimir-store-gateway-0`                  | `mimir-store-gateway-0`  | Mimir store-gateway cache/local state; blocks use SeaweedFS S3               | StatefulSet with one replica and `local-path-hetzner`. Needs monitoring Helm value migration.                                                      |
| `pvc-64142566-782b-413f-8393-5862bc552d78` | `tana-mcp/mcp-valkey-mcp-valkey-1`                          | `mcp-valkey-1`           | Tana MCP facade OAuth/session state Valkey replica                           | Master is already `mcp-valkey-0` on `talos-kimsufi-worker-0`; this is a removable old-site replica after replacement/scale-down cleanup.           |

### `talos-vps-worker-1`

| PV                                         | PVC                          | Pod                         | Purpose                                                                        | Notes                                                                                                                                                                   |
| ------------------------------------------ | ---------------------------- | --------------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pvc-c31a81bb-5802-4aff-a267-8befa8f27f81` | `grocy-sf/grocy-config`      | `grocy-77fcb8bdd-grzmj`     | Grocy SF application config/data, including SQLite and uploads under `/config` | Deployment uses `Recreate` and region `hil`; migration needs copy/restore or accepted app downtime.                                                                     |
| `pvc-d1bb043e-a3f1-4d18-999e-0bb2da5a804f` | `grocy-vallejo/grocy-config` | `grocy-77fcb8bdd-tmq9z`     | Grocy Vallejo application config/data under `/config`                          | Same pattern as Grocy SF.                                                                                                                                               |
| `pvc-6bd96776-3bc7-482c-bfae-487b13754982` | `tana-mcp/tana-mcp-config`   | `tana-mcp-6778d8d56f-nm4xv` | Tana Desktop profile/config under `/home/tana/.config/tana`                    | This is an `hcloud-volumes` CSI volume, not local-path. It has `Retain` reclaim policy and volume handle `105665337`; moving it is different from local-path migration. |

## Operator Facts

Current cluster state:

- HelmRelease: `cluster/k8s/valkey/helmrelease.yaml`
- chart version: `0.24.0`
- running operator image: `quay.io/opstree/redis-operator:v0.24.0`
- local source checkout: `/home/agentydragon/code/redis-operator`
- latest local source tag checked: `v0.25.0`
- `quay.io/opstree/redis-operator:v0.25.0` exists; the OT Helm repository
  does not currently publish chart `0.25.0`

Relevant source findings:

- `RedisReplication` has no declarative `spec.masterNode`; the controller
  derives the master from live Valkey roles and writes `.status.masterNode`.
- The `*-master` service selects pods by the `redis-role=master` label; labels
  are reconciled by connecting to the pods and reading their live role.
- StatefulSet ordinals are still `0..N-1`; regular scale-down removes the
  highest ordinal first, so YAML cannot say "remove ordinal 0 but keep ordinal
  1" for the existing Valkey StatefulSet.
- `v0.25.0` is useful but does not solve declarative promotion. It improves
  master fallback when all replication pods restart and fixes Sentinel config
  persistence across container restarts.
- `additionalRedisConfig` is only reliable for our `valkey/valkey:8-alpine`
  pods when `GenerateConfigInInitContainer=true`, because the init container
  generates `/etc/redis/redis.conf` and starts Valkey with that file.

TODO: replace the chart `0.24.0` plus image-tag override with a normal chart
version bump after the OT Helm repository publishes a `redis-operator` chart
for `v0.25.0` or newer.

If we bump for this migration, use it as a Phase 0 hardening step. Keep the
chart at `0.24.0` and override the operator/init image tags:

```yaml
values:
  redisOperator:
    imageTag: v0.25.0
    initContainerImageTag: v0.25.0
  featureGates:
    GenerateConfigInInitContainer: true
```

## Why Not "Just YAML" On The Existing CR

For the current `manifold-valkey` pair, the old master is
`manifold-valkey-0` on `talos-vps-worker-0`; the Kimsufi replica is
`manifold-valkey-1`.

A same-CR Git change can pin future pods to Kimsufi, but it cannot express all
of this atomically:

1. promote `manifold-valkey-1`;
2. make `manifold-valkey-0` follow it;
3. delete only the VPS-bound ordinal/PVC;
4. keep the service endpoint stable throughout.

The operator has no desired-master field, and StatefulSet semantics do not let
us remove ordinal 0 while keeping ordinal 1. The low-downtime way to do that is
a data-plane command (`REPLICAOF NO ONE` on the Kimsufi replica and
`REPLICAOF <new-master>` on the old master), whether issued by `kubectl exec`
or by a Git-applied Job. That keeps the existing service name, but it is still
an imperative role change.

## GitOps Replacement Path

This path avoids imperative promotion by creating a new Kimsufi-only
`RedisReplication`, letting it replicate from the old master, then cutting the
consumer to the new service. It does not mutate the existing StatefulSet
ordinals.

This is suitable for the MCP facade Valkeys because they hold OAuth/session
state. For strictly lossless state, insert a brief app write pause before the
detach/cutover step. Without that pause, writes that land on the old master
after the final catch-up check but before the app restarts against the new
Valkey can be lost.

### Phase 0: Operator Prep

Decide whether to bump the operator image and enable
`GenerateConfigInInitContainer`. If enabling the feature gate, roll this out and
verify the existing Valkey pods stay healthy before creating any replacement
Valkey:

```bash
kubectl -n valkey-system get deploy redis-operator -o wide
kubectl get redisreplication -A -o wide
kubectl get pods -A -l redis_setup_type=replication -o wide
```

### Phase 1: Add Kimsufi Followers

For `manifold-mcp`, add a second Valkey CR with a distinct name and Kimsufi-only
storage. The extra config makes both new pods start as replicas of the old
master service. Use size 2 so the final replacement remains replicated across
the two Kimsufi workers.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: manifold-valkey-kimsufi-replica-config
  namespace: manifold-mcp
data:
  redis-additional.conf: |
    replicaof manifold-valkey-master.manifold-mcp.svc.cluster.local 6379
---
apiVersion: redis.redis.opstreelabs.in/v1beta2
kind: RedisReplication
metadata:
  name: manifold-valkey-kimsufi
  namespace: manifold-mcp
  annotations:
    description: Replacement Kimsufi Valkey for Manifold MCP OAuth state
spec:
  clusterSize: 2
  redisConfig:
    additionalRedisConfig: manifold-valkey-kimsufi-replica-config
  kubernetesConfig:
    image: valkey/valkey:8-alpine
    imagePullPolicy: IfNotPresent
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
  storage:
    volumeClaimTemplate:
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: local-path-ovh
        resources:
          requests:
            storage: 1Gi
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: topology.kubernetes.io/zone
                operator: In
                values: ["hil-ovh"]
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app: manifold-valkey-kimsufi
          topologyKey: kubernetes.io/hostname
```

Commit and push through Flux. Verify the new pod is on a Kimsufi worker and is
replicating from the old service:

```bash
kubectl -n manifold-mcp get pod -l app=manifold-valkey-kimsufi -o wide
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-0 -- valkey-cli role
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-1 -- valkey-cli role
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-0 -- valkey-cli info replication
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-0 -- valkey-cli info persistence
```

Expected: role is `slave`, `master_link_status:up`, and persistence is enabled.

### Phase 2: Stop Writers

Pause the consumer by Git before detaching the new Valkey. This avoids losing
writes between the final replication catch-up check and the app restart against
the new service:

```yaml
spec:
  replicas: 0
```

Commit, push, and wait until the app pod is gone. Then re-check the replacement
Valkey's replication status.

### Phase 3: Detach The Replacement

In one Git change:

- remove `redisConfig.additionalRedisConfig` from
  `manifold-valkey-kimsufi`;
- remove the replica config `ConfigMap` from kustomization;

Push and wait for Flux. The two replacement pods will restart as standalone
masters, then the operator should choose one as master and configure the other
as a replica. Verify before unpausing the app:

```bash
kubectl -n manifold-mcp get pod -l app=manifold-valkey-kimsufi -L redis-role -o wide
kubectl -n manifold-mcp get endpointslice -l kubernetes.io/service-name=manifold-valkey-kimsufi-master -o wide
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-0 -- valkey-cli role
kubectl -n manifold-mcp exec manifold-valkey-kimsufi-1 -- valkey-cli role
```

Expected: exactly one pod is `redis-role=master`, the new master service has
one endpoint, and the other pod is a replica.

### Phase 4: Cut Over And Unpause

In one Git change:

- set `MCP_FACADE_PERSISTENCE__HOST` to
  `manifold-valkey-kimsufi-master.manifold-mcp.svc.cluster.local`;
- restore the consumer deployment to `replicas: 1`.

Push and wait for Flux. Verify:

```bash
kubectl -n manifold-mcp get deploy manifold-mcp
kubectl -n manifold-mcp logs deploy/manifold-mcp -c facade --tail=100
```

Expected: the facade is healthy and using the new Kimsufi Valkey service.

### Phase 5: Retire Old Valkey

After the consumer has been stable on the new service, remove the old
`manifold-valkey` CR from Git. The local-path PVs use `Delete` reclaim policy,
so the old VPS-bound PV should disappear after the CR and PVC are removed.

Verify no remaining Manifold Valkey storage is on a VPS worker:

```bash
kubectl get pv -o wide
kubectl -n manifold-mcp get pvc
kubectl -n manifold-mcp get pod -o wide
```

## Rollback

Before Phase 3, delete the replacement CR and ConfigMap from Git; the consumer
still points at the old `manifold-valkey-master` service.

After Phase 4, rollback is a Git change that points
`MCP_FACADE_PERSISTENCE__HOST` back to
`manifold-valkey-master.manifold-mcp.svc.cluster.local`. Any writes accepted by
the replacement after cutover will not automatically flow back to the old
Valkey.

## Paving Protocol For The First Run

Use `manifold-mcp` as the trial because its old master is the only Valkey master
currently on `talos-vps-worker-0`, and the state is OAuth/session persistence.

Before pushing live changes:

1. verify whether the Helm repository exposes an operator chart newer than
   `0.24.0`, and whether `quay.io/opstree/redis-operator:v0.25.0` exists;
2. pause `manifold-mcp` during detach and cutover;
3. commit Phase 0 by itself if enabling the feature gate or bumping the image;
4. run Phases 1 through 5 as separate Git commits, recording every Flux or
   operator surprise back into this runbook.
