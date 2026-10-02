# Runner directory: discovery independent of the integration app

Status: **proposed extraction and interface, not implemented.** The
[notification plan](notifications.md) needs runner discovery without product Thread lookup or runners
calling the notification service. Extract that responsibility from the integration app so the app and
other Agentplane services can use the same inventory.

## Boundary

The directory lists runners, their ServiceAccount authority, current endpoints, and lifecycle state.
It does not own conversations, app Threads, subscriptions, Action Decisions, command queues, or
sandbox provisioning. A published endpoint is not proof that any particular harness is running.

Existing code to extract from:

- [`SandboxInventory`](../app/inventory.py) and [`LiveIndex`](../app/live.py) observe managed Sandbox
  and Pod resources, including configured ServiceAccounts, immutable UIDs, and current addresses.
- [`Runners`](../app/agent_runtime/runner/runners.py) resolves sandbox inventory to runner clients.
- [`EventLogStore.runner_session`](../app/agent_runtime/events/event_log.py) maps app Thread IDs to
  runner sessions. That mapping stays app-owned; notifications must not depend on it.

For v1, a controller inside the directory derives registrations from trusted managed Kubernetes
resources. The provisioning component continues to create those resources. Runners do not call the
notification service or self-register with this directory. Do not expose generic caller-supplied
endpoint registration just because a future non-Kubernetes runner might need it.

The directory alone interprets the hosted runtime's provisioning resources. A notifications client
uses runner IDs and ServiceAccount associations, not sandbox ownership discovery. Kubernetes access
must be limited to the configured inventory; it is not permission to proxy arbitrary cluster traffic.

## Identity and lifetime

A directory record needs:

- **`runner_id`:** an opaque stable identity for the runner's retained session storage, not its Pod IP,
  Pod name, or a reusable sandbox name. Normal Pod replacement retaining that storage keeps the ID.
  Replacing/discarding the storage must not reuse the ID. Provisioning must establish this binding;
  do not pretend the current code already exposes a suitable storage-incarnation identifier.
- **`service_account`:** the authenticated authority associated with that runner, represented by
  namespace and name for the initial single-cluster deployment. Derive it from trusted provisioning
  state, never an arbitrary registration claim. A future multi-cluster directory needs cluster-qualified
  account identity rather than treating identical namespace/name pairs as the same principal.
- **`lifecycle`:** `active` or `retired`. Active includes temporarily unavailable runners. Retirement
  requires authoritative permanent removal, not an expired heartbeat, failed probe, or broken watch.
- **`endpoint`:** a tagged `published` or `unavailable` value. A published endpoint contains the gRPC
  target and the expected transport peer identity; an unavailable value contains a reason instead.
  Retired records have no usable endpoint. No credential is included in a directory response.
- **`revision` and `observed_at`:** a monotonically advancing record revision and observation time,
  so a consumer can identify route changes and diagnose stale state. Time alone does not authorize reuse.

UID-based source associations protect against Kubernetes name reuse. Pin the association between a
runner and its ServiceAccount; changing authority requires explicit retirement/rebinding policy,
not silently granting a new account the old runner's sessions. Settle the concrete storage identity,
source-deletion/retirement rules, and account-recreation handling before implementing the reconciler.

Maintain service-owned durable registration/retirement metadata where the source resources cannot
reconstruct it. Do not query integration-app tables or start a second authoritative session database.
If PostgreSQL is used, the directory owns its state separately from notification inboxes. Exact storage
layout and retirement-record retention are implementation choices, not settled by this interface.

## Proposed HTTP interface

These paths and field names are a concrete proposal, not a deployed API. Use the shared workload
identity authentication foundation for callers. Separate authentication from which runner records a
caller may discover. Ordinary workloads may discover records under their own ServiceAccount; trusted
app/notification service identities may discover accounts within their configured scope. A filter is
not an authorization grant. Never accept an untrusted caller's claimed original principal as proof.

### `GET /v1/runners`

List authorized runners. Optional filters: `service_account_namespace`, `service_account_name`, and
`lifecycle`. With no account filter, an ordinary workload still sees only its own account. A trusted
service can explicitly select the account it authenticated on an upstream request, within its own
authorized inventory scope. Support bounded pages using `limit` and an opaque `page_token`.

An illustrative item (identifiers and endpoint are examples):

```json
{
  "runner_id": "runner-17",
  "service_account": {
    "namespace": "agentplane-staging",
    "name": "agent-example"
  },
  "lifecycle": "active",
  "endpoint": {
    "kind": "published",
    "target": "runner-17.runners.example:443",
    "tls_server_name": "runner-17.runners.example"
  },
  "revision": 42,
  "observed_at": "2026-10-02T12:00:00Z"
}
```

A list response wraps records in `items` and supplies `next_page_token` when another page exists.
Pagination must not cause records to be silently skipped or duplicated within a promised snapshot;
choose consistent snapshot paging or an explicitly restartable revision contract. A single-runner
lookup is authoritative for the attempted route, not an old list page.

### `GET /v1/runners/{runner_id}`

Get one authorized record, including an unavailable/retired record. Example endpoint when temporarily
unavailable: `{"kind": "unavailable", "reason": "no_current_endpoint"}`. This is not retirement.

Distinguish a known runner with no endpoint from a missing/inaccessible ID and from directory/source
failure. Return a service-unavailable error when the authoritative inventory cannot be consulted within
the chosen freshness contract; do not translate a failed Kubernetes watch into an empty list or deletion.
Unauthorized and nonexistent IDs can share a not-found response to avoid disclosing inventory, but
clients must never interpret that response alone as authoritative retirement.

### Later: `GET /v1/runners/changes?after_revision=...`

A resumable change feed can reduce discovery/reconnect latency. It is not required for v1: explicit
lookups and bounded reconciliation suffice. A future feed needs a directory-wide cursor distinct from
record revisions, snapshot-to-follow consistency, and explicit retention-gap/resnapshot behavior.
Do not promise those semantics merely by adding SSE around an in-memory watch.

### Deliberately absent in v1

- No public `register`, `heartbeat`, or `delete` endpoint. Managed-resource reconciliation owns them.
  A later trusted provisioner API for external runners must define endpoint validation, ownership,
  replacement, and retirement; ordinary agents cannot register arbitrary connection targets.
- No Thread lookup, app database access, session creation/resume, or notification endpoint.
- No command proxy, transcript copy, or universal credential/token vending endpoint.
- No directory-owned session list. Clients use the existing runner `ListSessions` and `Attach` RPCs.

## Session scope and routing

Notification requests are authorized under the caller's ServiceAccount, not by resolving the caller
into a sandbox or authenticating a product Thread. The agent always supplies its session identifier;
no server chooses a "current" session.

A runner session ID is only unique within its runner's retained state. **Proposed addressing:** include
`runner_id` alongside `session_id`, supplied in agent context. The notification inbox/subscription scope
is then the authenticated ServiceAccount plus that qualified session identity. This avoids adding an
SA-wide session-ID uniqueness rule or scanning every runner on each request.

If instead the API accepts only `(ServiceAccount, session_id)`, first establish uniqueness within that
account, then resolve via the directory's runner list and runner `ListSessions`, persisting the resulting
binding. Reject conflicting matches; an unavailable candidate is not evidence that no conflict exists.
Never choose the first match or silently retarget an existing subscription. The qualified-ID shape is
the recommendation here, not a previously implemented guarantee.

With qualified IDs, delivery is:

1. Notifications authenticates its caller, derives the owning ServiceAccount, and obtains the explicit
   `runner_id` and `session_id` from the request.
2. It authenticates as its own service identity to the directory, looks up the runner, and verifies the
   returned ServiceAccount association matches the resource owner. No caller-supplied address is used.
3. It validates a new session binding through the runner. V1 may require an available runner for new
   bindings; existing subscriptions survive downtime. Do not create an unknown session implicitly.
4. It opens its own authenticated `Attach` connection without a session spec. The `Attached` state,
   not directory readiness, tells it whether the harness is running. Send notices only when running.
5. On endpoint change, re-resolve the same runner identity, verify the transport peer, and reconcile
   receipts using the original command IDs. A new endpoint is not a license to change session ownership.

Service-to-runner authentication remains a separate implementation requirement: directory discovery
is not a credential or permission to connect. The notification service is trusted with the destination's
ordinary protocol/history, with no new command-level RBAC. Choose authenticated encrypted transport
and runner identity checks; JWT is still only a candidate, and the app need not issue Thread tickets.

## Extraction sequence

1. Define and provision stable runner/storage identity and its ServiceAccount binding; pin endpoint
   replacement and retirement semantics before exposing an authorization-relevant lookup.
2. Extract managed-resource runner inventory into the independent directory, with authenticated scoped
   list/get operations, freshness/error behavior, and owned durable metadata as needed.
3. Migrate the integration app's runner-discovery client to this API. Keep product Thread mapping,
   provisioning UI, session management, and projection in their current owners. Do not keep a parallel
   app-owned authoritative runner inventory for delivery after the cutover.
4. Add notification routing as another client, settle qualified session IDs, and supply those IDs in
   agent context. Implement runner connection authentication rather than trusting returned IP addresses.

The existing Sandbox UI can still observe provisioning state for its own purposes; extraction concerns
runner discovery, not moving all Kubernetes management into a new service.

## Acceptance and deferred work

- No runner-to-notification registration or callback, and no app Thread lookup in notification routing.
- ServiceAccount-scoped discovery rejects unauthorized filters/lookups and ignores forged ownership.
- Multiple sessions in one authority remain mutually accessible; qualified session IDs cannot collide
  across runners. A session is never selected implicitly or created as a side effect of discovery.
- Normal Pod replacement preserves runner identity when storage survives; name/IP reuse or storage
  replacement cannot redirect old subscriptions or leak old inboxes to a new account.
- Unavailability, watch failure, and permanent retirement are distinct. Restart recovers lifecycle
  metadata; transient outages do not cancel subscriptions. Consumers do not treat list absence as deletion.
- The app and notifications use the same directory API; notifications works without the app's process,
  database, or delivery attachment once its session identifiers are supplied.
- Session inventory and receipts remain runner-owned. Directory endpoint publication never claims
  harness delivery or initiates resume.

Later: external-runner provisioner registration, a durable change feed, multi-cluster identity, and any
extraction of product Thread ownership. None requires coupling runners to notifications.
