# Runbook: SeaweedFS Bucket CR adoption

**Status (2026-05-27)**: Resolved by upgrading SeaweedFS to 4.x. 5 of 6
existing Bucket CRs (attic, augur-assets, mimir-blocks, mimir-ruler,
tempo) adopted automatically when the filer rolled to 4.29. Only
`loki` stayed Failed due to a non-default filer mode (see below).

## Root cause

SeaweedFS 3.93 (the version that shipped via `chrislusf/seaweedfs:3.93`
in our previous Seaweed CR) does NOT register the
`iam_pb.SeaweedIdentityAccessManagement` gRPC service on any daemon.
The symbol is in `weed/pb/iam_pb/iam_grpc.pb.go` but never registered.

The seaweedfs-operator's bucket controller (`NewSwadminBucketAdmin`)
issues `weed shell` commands (`s3.bucket.access`, `s3.bucket.owner`),
which internally call the filer's `iam_pb` gRPC service. In 3.93 those
calls hit `Unimplemented` → reconcile fails with `AccessFailed` → the
operator never completes its post-create steps → every Bucket CR loops
in `Failed/BucketAlreadyExists`.

Commit `f41925b60` ("Embed IAM API into S3 server") landed in
SeaweedFS **4.03**. From that release on, the filer unconditionally
registers `iam_pb` on its existing gRPC port (18888 by default)
whenever `credentialManager` initializes successfully — which it
always does, even without `filer.s3.enabled` and without `-iam` flag.
Auth is opt-in via `jwt.filer_signing.key`; unauthenticated by default,
matching the rest of the filer's gRPC surface.

## Fix

Bump the Seaweed CR's image to a 4.x version. Currently pinned at
`chrislusf/seaweedfs:4.29` in
`cluster/k8s/seaweedfs/cluster/seaweed.yaml`.

The 3.93 → 4.29 upgrade was safe: no on-disk format changes for the
leveldb2 filer store, volume `.dat`/`.idx`, or `s3-config.json`. The
upgrade rolls the seaweed-operator-managed StatefulSets and Deployment
on next Flux reconcile — see `git log cluster/k8s/seaweedfs/cluster/seaweed.yaml`
for the version-bump commit.

After the rollout, existing Bucket CRs that aren't `Ready` get
re-reconciled automatically on the operator's standard interval. Most
adopt within ~30s.

## Leftover: `loki` stuck Failed

Loki's CR stays `Failed/BucketAlreadyExists` after the upgrade because
its filer directory `/buckets/loki/` has Mode `0o471` instead of the
operator's default `0o777`. The operator interprets the non-default
mode as "this is someone else's bucket, refuse to adopt."

The 5 other buckets all have `Mode: 0o777` in their filer metadata, so
they adopted cleanly.

The mode is metadata only — loki keeps reading and writing logs fine
on 0o471. The Failed CR status is cosmetic.

Fix when convenient: chmod the bucket via `weed shell` (run inside a
filer pod or with port-forward + the `weed shell` binary):

```sh
kubectl -n seaweedfs exec -it sts/seaweedfs-filer -- weed shell -master=seaweedfs-master-0.seaweedfs-master-peer.seaweedfs:9333 <<EOF
fs.chmod -mode=0777 /buckets/loki
EOF
```

(Or `fs.chmod /buckets/loki 0777` depending on the shell command's
argument shape — check `fs.chmod help` first.)

Force a Bucket CR reconcile after the chmod and it should move to
`Ready`.

## How to verify iam_pb is registered

```sh
kubectl -n seaweedfs port-forward sts/seaweedfs-filer 18888:18888 &
grpcurl -plaintext localhost:18888 list
# Expected output:
#   filer_pb.SeaweedFiler
#   grpc.reflection.v1.ServerReflection
#   grpc.reflection.v1alpha.ServerReflection
#   iam_pb.SeaweedIdentityAccessManagement
```

The fourth entry is what was missing in 3.93.

## Filer startup log to look for

```text
filer.go:451 Registered IAM gRPC service on filer (unauthenticated;
  set jwt.filer_signing.key in security.toml to require admin Bearer
  token)
```

This line appears in the filer's stdout on 4.x startup when
`credentialManager` initialized successfully (which is always).

## Notes that turned out to be wrong (kept for the record)

An earlier version of this runbook attributed the failure to an
operator bug ("creates buckets with `owner: ""` and can't recognize
its own creates"). The actual issue was simpler: the filer just wasn't
running the IAM gRPC service at all, so every operator call returned
`Unimplemented`. The "BucketAlreadyExists" was a downstream symptom,
not an adoption-logic bug. Confirmed by reading both the
seaweedfs-operator 1.0.19 source (`internal/controller/swadmin/`,
`internal/controller/bucket_admin.go`) and the seaweedfs 3.93 vs 4.29
source (`weed/command/filer.go`, `weed/pb/iam_pb/iam_grpc.pb.go`)
locally cloned at `~/code/seaweedfs-operator` and `~/code/seaweedfs`.
