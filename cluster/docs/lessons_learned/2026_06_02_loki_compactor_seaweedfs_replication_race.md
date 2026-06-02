# Loki Compactor Init Failure from Corrupt S3 Object

**Date**: 2026-06-02
**Status**: Resolved (specific instance); root cause partially understood.

## Symptom

`loki-backend-{0,1}` crashed at startup 100+ times with:

```text
init compactor: failed to init delete store: unexpected EOF
error initialising module: compactor
```

Loki's compactor opens `loki/index/delete_requests/delete_requests.gz`
unconditionally on startup. The S3 read returned `unexpected EOF` before
the metadata-reported size (135B) was reached — the actual on-disk blob
was truncated.

This blocked log ingestion (`loki-write-*` couldn't talk to a healthy
backend).

## Fix Applied

1. Identified the corrupt object from inside the cluster:
   ```bash
   AKID=$(kubectl get secret -n loki loki-s3-credentials -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
   SKEY=$(kubectl get secret -n loki loki-s3-credentials -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)
   kubectl run -n loki loki-bucket-inspect --image=minio/mc:latest --rm -it --restart=Never -- \
     sh -c "mc alias set sw http://seaweedfs-s3.seaweedfs.svc:8333 '$AKID' '$SKEY'; mc cp sw/loki/index/delete_requests/delete_requests.gz /tmp/test"
   # → fails with "unexpected EOF" (exactly Loki's error)
   ```
2. Deleted the corrupt object: `mc rm sw/loki/index/delete_requests/delete_requests.gz`.
3. Restarted Loki backends: `kubectl delete pod -n loki loki-backend-0 loki-backend-1`.
4. Both backends came back `2/2 Running` in ~4 minutes; `Loki started`
   logged a clean init.

## Context

The corruption appeared during the OVH node rename project (see
<../../debug/2026-06-02-tofu-apply-hangs-from-rugged-mtu.md> and
<../../../plans/rename_ovh_nodes_role_neutral.md>). Each pilot deleted
the local-path PVC of one SeaweedFS volume server in sequence as part of
the per-node cleanup, relying on SeaweedFS replication
(`defaultReplication: "001"` — one extra copy on a different rack/node)
to preserve data.

`weed shell volume.list` after all renames confirms replication WAS
working: each volume ID (e.g. 171-210) appears on TWO `DataNode` blocks
(volume-1 and volume-2 entries), even though all three volume servers
are configured with the same `rack=hil-ovh-h109b04` identifier.
SeaweedFS appears to fall back to "place on a different DataNode" when
the rack constraint can't be satisfied across distinct racks.

So we did NOT lose 1/3 of the bucket. Only this one specific S3 object
was corrupt, and the rest of the `loki` collection (≈110MB across
6 volumes, 11k+ files) was intact.

## Open Question / Real Root Cause

Not certain what caused this specific object to become corrupt. Plausible
hypotheses:

1. **Replication race**: an in-flight write was acked by one volume server
   and added to the SeaweedFS filer's metadata DB before the second
   replica finished writing. When that first server's PVC was deleted
   shortly after, the surviving replica had a partial blob. Filer DB
   said "135 bytes"; the body on disk was shorter.
2. **Stale read during pod rotation**: SeaweedFS may have served a
   partially-written staging copy if a master/volume coordination message
   was lost during a node drain.
3. **Pre-existing corruption** the rename project didn't cause; we only
   noticed because the backend was forced to restart and re-read the
   file. Loki's normal operating pattern keeps this file cached in memory
   and only re-reads on restart.

We didn't gather pre-mortem evidence (e.g. attempting to read the file
right before deleting the volume PVCs that day), so we can't
definitively rule out (3).

## Hardening / Followups

- **Loki's compactor `init delete store` is a single point of failure.**
  No retry, no skip-on-corruption fallback for a 135-byte cursor file
  blocks the entire backend. Worth filing upstream or carrying a local
  patch.
- **Don't blindly trust S3 object size for integrity.** S3 metadata
  (filer DB row) can claim N bytes while the actual blob is shorter or
  garbage. When investigating data integrity, always do a full
  `mc cp` / `mc cat` rather than just `mc stat`.
- **When deleting PVCs of replicated storage in sequence**, give the
  replication system time to converge between deletions. A simple
  `weed shell volume.balance` (or just wait a few minutes) after each
  PVC delete would have surfaced any under-replicated volumes before the
  next pilot started.
- **SeaweedFS rack labels** are identical across all 3 volume servers.
  This is fine for our 1-DC cluster, but it means the `001` replication
  policy is satisfied by "any other DataNode" rather than "another rack".
  If we want true rack-failure tolerance in the future, the rack IDs
  need to actually differ.
