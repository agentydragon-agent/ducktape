# Existing-session access API

This is the first standalone Sandbox Service API slice. It can inspect, command, and
follow an **existing** runner session. It does not yet expose provisioning or session
creation, migrate app callers to HTTP, or start a second provisioning/ingestion process.

## Identity and destinations

Every operation uses the shared Pod-bound workload Bearer authenticator. Each request
performs TokenReview for the configured audience and accepted SA namespaces. A destination
always names its owner, Sandbox name **and UID**, and runner session ID:

```json
{
  "destination": {
    "owner": {"namespace": "example-sandboxes", "name": "example-runner-account"},
    "sandbox": "example-runner",
    "sandbox_uid": "40e373bd-2742-43de-8d1c-1ef97c4d4801",
    "session_id": "example-session"
  }
}
```

The owner is a request selector, not a forwarded identity. An ordinary authenticated SA
can address only itself; all sessions under that SA share its existing sandbox trust
boundary. `trusted_accounts` explicitly grants selected service SAs cross-account access.
It defaults to empty. A trusted client must still name the actual owner, and the service
checks that against the managed Sandbox's Pod template. No caller-supplied header, Thread
ID, Pod name, or URL establishes ownership or selects a runner endpoint.

Resolution is confined to the configured inventory namespace. Name reuse with another
Sandbox UID is rejected. The current ready, non-deleting Pod must have the expected
namespace/name/account and exactly one controller owner matching the Sandbox UID. A
successor Pod under the same Sandbox can replace its endpoint. Resolution is not an atomic
Kubernetes/runner transaction or cryptographic peer verification: runner RPC auth/TLS
remains an explicit follow-up, and deployment must enforce the intended network boundary.

## Operations

POST bodies carry the composite destination so the same explicit shape works for ordinary
agents and trusted services. All schemas are exposed in `/openapi.json`.

| Route | Additional body fields | Response |
| --- | --- | --- |
| `POST /v1/sessions/inspect` | None | Native runner `Attached` as protobuf JSON. |
| `POST /v1/sessions/commands` | `command`: native protobuf JSON; `after_cursor`: nonnegative runner-log cursor, default `0`. | Original `EventEntry` containing the exact matching `CommandAdmitted`. |
| `POST /v1/sessions/follow` | `after_cursor`: nonnegative runner-log cursor, default `0`. | SSE `entry` frames, each containing original `EventEntry` protobuf JSON. |

For example, add these fields to the destination body to submit a notice:

```json
{
  "command": {
    "commandId": "caller-chosen-stable-notice-id",
    "submitInput": {"text": "You have 7 inbox messages. Retrieve them using the notification service."}
  },
  "after_cursor": 0
}
```

All attachments omit `SessionSpec`: none of these operations creates a session, resumes
a harness, or wakes a sandbox. Command submission additionally requires a running harness.
Admission is neither harness confirmation nor inbox acknowledgement. On uncertain delivery,
reconcile using the unchanged ID/payload and a cursor before its possible admission; do not
allocate a new ID. There is no offline command queue.

A follow starts only after the runner answers Open. Each follow has a bounded lease
(default 30 seconds, configured maximum 60); reconnect with the last fully consumed cursor.
This reauthenticates and re-resolves the destination. Sending to a stalled HTTP consumer gets
at most five additional seconds before cleanup. There is no unbounded fan-out queue. A
midstream runner failure emits an `unavailable` transport frame, **not** a synthetic runner
Event. EOF, expiry, and disconnect convey no extra admission/confirmation evidence.

Typical errors: `401` invalid bearer, `403` unauthorized owner, `404` missing/stale Sandbox
incarnation, `409` runner refusal (including unknown or stopped session for commands),
`422` invalid input, `503` unavailable destination/backend, `504` uncertain receipt timeout.
A connection failure can happen after commitment: neither 5xx nor disconnect proves that a
command was rejected. Reconcile from runner evidence.

## State and deployment boundary

The first API follows only the surviving runner log. It has no database and never falls
back to app PostgreSQL. The app remains the existing retained-archive owner until an explicit
migration transfers that responsibility; this API does not provide history after runner state
is lost. No overlapping archive authority is introduced.

`//agentplane/sandbox_service:server` runs the service. Its settings use
`AGENTPLANE_SANDBOX_SERVICE_*` environment variables or corresponding kebab-case CLI flags.
Required settings are `sandbox_namespace` and `allowed_service_account_namespaces`;
`token_audience` defaults to the existing `agentplane-egress` workload audience. Kubernetes
access is in-cluster unless `kubeconfig` is supplied. `/healthz` is unauthenticated liveness,
not a claim that Kubernetes or a destination is ready.

This PR adds no deployment, network policy, egress credential rules, staging resources, or
app HTTP cutover. Before cutover: finish lifecycle/grant orchestration and backend session
configuration/prompt extraction; configure narrow Kubernetes read/TokenReview permissions;
audit both sides of runner network access; inventory/back up retained staging state; and
switch each migrated app path without leaving a permanent direct-runner bypass.
