# Staging GitHub acceptance — 2026-10-04

App **5188971** is enabled; the operator confirmed installation on all their repositories.
[Rollout proof](https://github.com/agentydragon/ducktape/issues/8956#issuecomment-5983967691): 2/2 ready replicas, successful migrations, Flux healthy; no database reset.

Verified on `agentydragon/ducktape`, without integration-app API calls:

- 13 real branch CI events (`workflow_run`, `check_run`, `check_suite`, `status`) reached inbox and harness.
- [A PR comment](https://github.com/agentydragon/ducktape/pull/8982#issuecomment-5984066218) produced one inbox entry matching both overlapping subscriptions.
- Reads preserved acknowledgement; the agent explicitly acknowledged through cursor 24 and cancelled test subscriptions.

Not proved: webhook-redelivery deduplication, restart recovery, revoked access, broader repository/event/fork coverage or negative ingress probes.
See [remaining work](../../plans/notifications.md). Debounce [#8988](https://github.com/agentydragon/ducktape/pull/8988) is not part of this deployed proof.

## Shared GitHub state rollout — 2026-10-09

PR [#9482](https://github.com/agentydragon/ducktape/pull/9482) merged as `00003af`.
Staging ran notification image `devel-20261009024342-00003af` with 2/2 updated, ready and
available replicas, no old replicas remaining, and zero restarts at the rollout check.
Both image-coupled migration init containers exited 0. Readiness passed on both replicas;
it checks worker tasks, PostgreSQL connectivity and the LISTEN connection.

An authenticated read of an existing cancelled PR subscription returned structured
`github.access` and `github.subject` observations. Shared repository access was currently valid,
with a successful refresh and no recorded error/retry deadline. New pods accepted webhooks
with HTTP 202. This proves rollout and basic status projection, not full behavioral acceptance.

CI passed for the merged change, including 70 GitHub notification tests covering normalized
entities, structured delivery-subject links, leases/generation fences, refresh reuse, expiry
rollback, migrations and required nullable response fields. Those are automated tests, not
live restart/revocation/fork acceptance.

Rollout logs also showed webhook HTTP 400 rejections. A subsequent bounded 35-minute log read
found 154 webhook 400 responses and 352 webhook 202 responses across the two replicas;
rejections are recurring, not a single startup blip. The current access log does not identify
an event or rejection reason. Diagnosis and remaining live verification stay open in the
[notification plan](../../plans/notifications.md#remaining-live-verification).
