# Sandbox Service API

## Agreed contract: protobuf/gRPC

**Implementation status:** the HTTP adapter documented below is transitional. The gRPC conversion
and app client cutover are not complete. Do not treat the HTTP routes as a second supported long-term
API. The [extraction plan](../plans/sandbox_service.md#transport-decision) records the transport decision.

The service will expose unary RPCs for inventory, explicit sandbox lifecycle, session inspection/
management, and command admission; session following will be server-streaming. Reuse the common
runner protobuf types for commands, snapshots, specs, events, and cursors. Inventory and provisioning
requests/responses also need typed protobuf messages, not generic JSON envelopes. This is a
service-level API, not a transparent proxy for the runner's bidirectional `Attach` RPC.

- Each session RPC carries an explicit owner, sandbox name and UID, and session ID. Sandbox-level
  operations omit the session ID. The service resolves endpoints internally.
- Authenticate workload bearers in `authorization` metadata with the shared principal resolver.
  Apply the same destination, cross-owner, and management authorization as the transitional adapter.
- Command submission returns the original matching native `CommandAdmitted` event entry, not a new
  service-authored receipt. Admission does not mean harness consumption or command completion.
- Following begins with a snapshot and then original event entries. Preserve source identity and
  per-reader replay cursors. Distinguish native stream closure, lease expiry, and backend failure;
  a transport disconnect alone says nothing about whether the session ended.
- Use gRPC deadlines/cancellation and standard status codes. Reconnect bounded follow leases with
  the last fully consumed cursor, rechecking identity and destination. Cancel runner attachments on
  every exit, including stalled or disconnected consumers.
- Do not automatically retry mutations. A timeout/unavailable response may follow commitment;
  reconcile command submission using its unchanged ID/payload and runner evidence. Sandbox creation
  is not currently idempotent; an uncertain create needs inventory reconciliation, not blind retry.

The app keeps its browser HTTP API. HTTP health probes can remain. This choice does not require
agent-facing subscription tools to use gRPC or introduce fine-grained RBAC inside the runner.

The service exposes logs retained by the runner on its state volume, with no additional archive.
Clients needing independent retention archive events themselves. The app keeps its current PostgreSQL
archive and consumes runner events through this service after cutover.

## Transitional HTTP implementation

The current standalone adapter exposes existing-session access and explicit bootstrap/open/resume.
An optional provisioning router also exposes Sandbox inventory and lifecycle operations. The session
operations described below require a currently running runner; they do not provision or wake a Sandbox.

## Identity and destinations

Every operation uses the shared Pod-bound workload Bearer authenticator. Each request
performs TokenReview for the configured audience and accepted SA namespaces. A destination
always names its owner and Sandbox name **and UID**. Session operations also require a
runner session ID (omit it for listing sessions and initializing a Sandbox):

```json
{
  "destination": {
    "owner": { "namespace": "example-sandboxes", "name": "example-runner-account" },
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

| Route                        | Additional body fields                                                                       | Response                                                                 |
| ---------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `POST /v1/sessions/inspect`  | None                                                                                         | Native runner `Attached` as protobuf JSON.                               |
| `POST /v1/sessions/commands` | `command`: native protobuf JSON; `after_cursor`: nonnegative runner-log cursor, default `0`. | Original `EventEntry` containing the exact matching `CommandAdmitted`.   |
| `POST /v1/sessions/follow`   | `after_cursor`: nonnegative runner-log cursor, default `0`.                                  | SSE `entry` frames, each containing original `EventEntry` protobuf JSON. |

For example, add these fields to the destination body to submit a notice:

```json
{
  "command": {
    "commandId": "caller-chosen-stable-notice-id",
    "submitInput": { "text": "You have 7 inbox messages. Retrieve them using the notification service." }
  },
  "after_cursor": 0
}
```

Read/follow/command attachments omit `SessionSpec`: none of these operations creates a session, resumes
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

## Explicit session management

- `POST /v1/sessions/list`: Sandbox destination without `session_id`; returns
  `{"sessions": [...]}` with native `SessionSummary` protobuf JSON. This is read-only.
- `POST /v1/sandboxes/initialize`: Sandbox destination; executes/replays **only** its stored
  binding's bootstrap and returns native `InitializeResult` protobuf JSON. A nonzero
  `exitCode` is a completed failed bootstrap, not success. No configured bootstrap is 409.
- `POST /v1/sessions/open`: session destination, optional `spec` (native `SessionSpec`
  protobuf JSON overrides), optional `setup_script`. Resolves stored concrete launch
  defaults without an app preset catalog, prepends backend-owned operational guidance and
  explicit destination context, runs the stored bootstrap, then sends native Open. A failed
  bootstrap prevents Open. Returns native `Attached`; setup can still be running, so this
  snapshot does not promise a ready harness. Follow/inspect for actual progress.
- `POST /v1/sessions/resume`: session destination only. Finds the runner's retained session
  and uses its exact stored spec. No current defaults, platform prompt, bootstrap, or setup
  script are reapplied. Missing sessions and failed/interrupted setup are refused (409).

Initialize/open/resume additionally require `manager_accounts`, an explicit allowlist that
is empty by default. Cross-owner management also requires `trusted_accounts`; neither list
implies the other. Delivery-only services do not gain launch authority from cross-owner
access. This is an HTTP lifecycle boundary, not command-level RBAC on the runner protocol.

When management is enabled, configure `agent_egress_api_url` and `agent_actions_service_url`
for the bundled platform instructions, or explicitly set `agent_instructions` (including
an intentional empty string). Stored session specs are never rewritten after a deployment.
Open retries must use the same destination and launch inputs. Changed defaults/instructions
can cause an Open retry to conflict: inspect/list retained state and explicitly resume,
never silently adopt a different spec or allocate another session ID. The runner owns
idempotence for bootstrap, session identity, and setup. There is no service-side queue.

Resume also requires the native harness's retained conversation, not just a runner spec.
For example, the pinned Claude harness can reject resuming an empty conversation that has
never persisted a turn. This API surfaces that refusal; it does not fabricate a replacement
conversation or claim that runner admission proves native persistence. Improving empty-native-
conversation resume is a runner follow-up, not part of this service extraction.

Management requests are bounded by `lifecycle_timeout_s` (default 300). A timeout or client
loss does not prove that bootstrap, setup, or launch did not happen. Reconcile via the same
runner identity and retained state; an exact bootstrap retry replays its terminal result.
List requests use `admission_timeout_s`. Read/command/follow still never start a harness.

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
app HTTP cutover. Before cutover: finish Sandbox lifecycle/grant orchestration; configure
narrow Kubernetes read/TokenReview permissions;
audit both sides of runner network access; inventory/back up retained staging state; and
switch each migrated app path without leaving a permanent direct-runner bypass.
