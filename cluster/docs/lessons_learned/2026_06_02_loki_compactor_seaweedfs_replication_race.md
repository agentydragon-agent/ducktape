# Loki Compactor Init Failure from SeaweedFS Replication Race

**Date**: 2026-06-02
**Status**: Resolved

## Root Cause

A single S3 object (`loki/index/delete_requests/delete_requests.gz`) was
corrupted: S3 metadata reported it as 135 bytes, but reads returned
`unexpected EOF` before reaching that size — the actual on-disk blob was
truncated.

This blew up Loki at every startup. The compactor's `init delete store`
step opens this object unconditionally; the truncated read aborted Loki
before any other module came up:

```text
init compactor: failed to init delete store: unexpected EOF
error initialising module: compactor
```

`loki-backend-{0,1}` crashed in this loop 100+ times, taking down log
ingestion (`loki-write-*` couldn't talk to a healthy backend).

The trigger was the OVH node rename project (see
<../../debug/2026-06-02-tofu-apply-hangs-from-rugged-mtu.md> and
<../../../plans/rename_ovh_nodes_role_neutral.md>). Each pilot deleted
the local-path PVC of one SeaweedFS volume server in sequence, relying
on SeaweedFS replication (`defaultReplication: "001"` — one extra copy
on a different rack/node) to preserve data across the rolling rotation.

For the vast majority of objects that worked correctly:
`weed shell volume.list` after all 5 renames showed the `loki` collection
healthy at ~110MB across 6 active volumes with thousands of files intact.

For `delete_requests.gz` it didn't. Suspected sequence:

1. Loki writes a new `delete_requests.gz` body to the S3 endpoint.
2. SeaweedFS S3 gateway accepts the write, places it on one volume
   server, and ACKs the client.
3. Replication to the second volume server is in flight when that first
   server's PVC gets deleted (i.e. we drained the host and then deleted
   the hostname-pinned `mount0-seaweedfs-volume-*` PVC).
4. The replication target ends up with a partial blob whose chunked
   metadata says "this object is N bytes" but whose actual content
   stream truncates earlier.
5. The volume server that had the complete copy is gone; subsequent
   reads come from the surviving truncated copy.

The replication policy gave us durability against losing one volume
server's data. It didn't (and conceptually can't) protect against losing
the server that held the only complete copy of an in-flight write
before the second replica was committed.

## Fix Applied

1. Identified the corrupt object by listing the bucket from an in-cluster
   `mc` pod and seeing `mc cp` fail on this specific path with the same
   `unexpected EOF` error Loki was reporting.
2. `mc rm` the corrupt object.
3. `kubectl delete pod -n loki loki-backend-{0,1}` to restart the
   StatefulSet pods.

Both backends came back `2/2 Running` within ~4 minutes; Loki logged
`Loki started startup_time=4.14s` and the scheduler joined the ring.
Ingestion resumed.

## Prevention / Hardening

- **`defaultReplication: "001"` is durable against losing one volume
  server's data, NOT against losing in-flight writes.** When rotating
  volume servers, wait for SeaweedFS to confirm replication has caught
  up before deleting the next server. `weed shell ec.balance` /
  `volume.balance` don't directly help; the right signal is to drain
  workloads that write to S3 during the rotation, or accept that some
  recent writes may need to be reconstructed.
- **Loki's compactor is brittle to a single corrupt index file.** The
  `init delete store` step has no retry or skip-on-corruption fallback.
  When investigating Loki crashloops with `unexpected EOF`, always look
  for a tiny corrupt object in `index/delete_requests/` or
  `index/loki_index_*/` before assuming wider data loss.
- **`mc cp` is the diagnostic.** A `Size:` from `mc stat` matching what
  you'd expect doesn't prove the object reads cleanly — only a
  successful read does.

## Diagnostic Recipe

```bash
# 1. Inspect the Loki S3 bucket from inside the cluster.
AKID=$(kubectl get secret -n loki loki-s3-credentials -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
SKEY=$(kubectl get secret -n loki loki-s3-credentials -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)
kubectl run -n loki loki-bucket-inspect --image=minio/mc:latest --rm -it --restart=Never -- sh -c "
  mc alias set sw http://seaweedfs-s3.seaweedfs.svc:8333 '$AKID' '$SKEY'
  mc ls --recursive sw/loki/index/ | head
  # Look for any object that fails to read:
  for f in \$(mc ls --recursive sw/loki/ | awk '{print \$NF}'); do
    mc cat sw/loki/\$f >/dev/null 2>err && rm err || echo \"corrupt: \$f (\$(cat err))\"
  done
"

# 2. Delete the corrupt object(s).
mc rm sw/loki/index/delete_requests/delete_requests.gz

# 3. Restart Loki backends.
kubectl delete pod -n loki loki-backend-0 loki-backend-1
```
