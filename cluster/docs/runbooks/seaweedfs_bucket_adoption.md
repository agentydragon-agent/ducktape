# Runbook: SeaweedFS Bucket CR adoption (currently broken)

**Last attempt**: 2026-05-27 (this session).

**Status**: Adoption is **not possible** with the current
`seaweedfs-operator` due to an operator bug — buckets in
`Failed/BucketAlreadyExists` phase cannot be promoted to `Ready`
even after the bucket is deleted and the operator recreates it
itself. Workaround documented below.

## Problem statement

After Phase 1 (per-tenant ESO restructure of s3-config) all 5
existing Bucket CRs in this cluster are in `status.phase: Failed`:
`attic`, `augur-assets`, `loki`, `mimir-blocks`, `mimir-ruler`,
`tempo`. All with the same `reason: BucketAlreadyExists`,
`message: bucket "<name>" already exists on cluster "seaweedfs" and
was not created by this resource; adoption is not supported`.

The functional state is fine — buckets exist in the filer, s3
clients read/write happily — but `Flux Kustomization` resources
with `spec.wait: true` that include these CRs are stuck in
`Ready=Unknown`, because the CR health gate never resolves.

## What naive "delete + let-CR-recreate" gets you

Backup data: `aws s3 sync s3://<bucket>/ /tmp/backup/`. Then delete
the bucket dir + contents via filer HTTP
(`kubectl port-forward svc/seaweedfs-filer 8888:8888` first):

```bash
curl -X DELETE "http://localhost:8888/buckets/<name>/?recursive=true"
curl -X DELETE "http://localhost:8888/buckets/<name>"
```

Watch the Bucket CR. Within a couple of minutes the bucket reappears
in filer, the CR returns to `Failed/BucketAlreadyExists`, status was
never Ready.

**Root cause of the immediate failure**: SeaweedFS auto-creates a
bucket directory the first time _anything_ references the bucket
name — including the s3 gateway responding to an identity's
`<Verb>:<bucket>` action in s3-config. So between your delete and
the operator's next reconcile, the s3 gateway recreates the bucket
via the identity's bucket-scoped actions.

## What the "proper-quiesce" pattern gets you

To stop the s3 gateway from auto-creating, temporarily remove the
identity that references the bucket. Sequence (tested for
`augur-assets`):

**Step 1: Backup.** Port-forward the s3 gateway
(`kubectl port-forward svc/seaweedfs-s3 8333:8333`), then
`aws --endpoint-url http://localhost:8333 s3 sync s3://<bucket>/ /tmp/<bucket>-backup/`
with the tenant's `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

**Step 2: Remove the identity from gitops.** Delete
`cluster/k8s/seaweedfs/secrets/identities/<bucket>.sops.yaml`,
comment it out of `kustomization.yaml`. Commit + push. Wait for
Flux + ESO + s3 gateway pod rollout (Reloader). Verify with
`kubectl -n seaweedfs get secret seaweedfs-s3-config -o jsonpath='{.data.seaweedfs_s3_config\.json}' | base64 -d | jq '[.identities[].name]'`
— `<bucket-user>` should be gone.

**Step 3: Delete the bucket via filer.** Same `curl -X DELETE`
calls as the naive pattern; both should return 404 on subsequent
HEAD.

**Step 4: Force operator reconcile** —
`kubectl -n seaweedfs annotate bucket <name> reconcile-quiesce="$(date +%s)" --overwrite`.
Operator logs will show
`controller.Bucket created bucket {"owner": ""}`, then a
follow-up `reconcile failed {"reason": "AccessFailed"}` (the user
we just removed doesn't exist), then
`reconcile failed {"reason": "BucketAlreadyExists"}` on the next
loop iteration.

**Step 5: This is where the operator bug bites.** The operator
created the bucket fresh with `owner: ""` (empty). On the next
reconcile, the operator's "is this bucket mine?" check compares the
bucket's owner attribute against its own identity — empty != operator
— so it concludes "not mine, refuse adoption" and returns to
`BucketAlreadyExists`. The `AccessFailed` is a secondary issue (the
user we just removed in step 2 doesn't exist when the access wiring
tries to fire).

**Step 6: Restore the identity** (`git revert` the WIP commit, push).
Wait for reconciles + pod rollout.

**Step 7: Restore data.**
`aws --endpoint-url http://localhost:8333 s3 sync /tmp/<bucket>-backup/ s3://<bucket>/`.

**Step 8: End state.** Bucket CR remains in
`Failed/BucketAlreadyExists`. Live service works exactly as before —
filer + s3 gateway never lost the bucket from their working state.
The Bucket CR `access` rules also never get applied (operator gives
up before reaching the access wiring), so per-bucket IAM scoping
relies on the global `Read:<bucket>` / `Write:<bucket>` actions in
s3-config — which is what's actually enforcing access today anyway.

## Workaround for Flux `wait: true` gates

If a Flux Kustomization includes a Bucket CR and uses `wait: true`,
the kustomization will stick at `Ready=Unknown` / `HealthCheckFailed:
timeout waiting for: [Bucket/...status: 'InProgress']` forever.
Options:

1. **Drop `wait: true`** on the consuming Kustomization. The
   Kustomization moves to Ready after apply, regardless of Bucket CR
   health. Cleanest for now.
2. **Exclude the Bucket CR from health checks** via
   `spec.healthChecks` listing only resources you actually want to
   gate on. More surgical but verbose.
3. **Drop the Bucket CR entirely** and rely on the bucket existing
   implicitly via the identity's bucket-scoped actions. Loses the
   declarative `anonymousRead` / `objectLock` / `versioning` surface.
   Not recommended.

## When this can be revisited

The right long-term fix is in the SeaweedFS operator:

- It should stamp `owner: <operator-instance-id>` (or any non-empty
  value) on buckets it creates so subsequent "is this mine?" checks
  succeed.
- OR add a `force-adopt: true` annotation on the Bucket CR for
  explicit adoption opt-in.

Either lands → we can retry the proper-quiesce pattern and get a
Ready CR. Without that fix, no migration path produces a `Ready`
Bucket CR for buckets that already exist.

## What we did NOT use but might be relevant later

- **Operator scale-down + restart**: not tried. Theory was scaling
  the operator to 0 replicas might let us delete the bucket cleanly,
  then scale up for a fresh "create" path. But the operator's create
  itself sets `owner: ""`, so this wouldn't help with the deeper
  bug.
- **Direct filer attribute manipulation**: SeaweedFS filer exposes a
  metadata-edit API. In principle we could set an owner attribute on
  an existing bucket so the operator considers it adopted. Not
  tried; would require reverse-engineering what the operator looks
  for.
- **Operator upgrade**: the cluster runs `seaweedfs-operator`
  v0.1.22. Newer versions may fix the owner-stamping. Check upstream
  before retrying.
