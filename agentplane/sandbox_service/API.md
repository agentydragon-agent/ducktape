# Sandbox Service API

The service uses [protobuf/gRPC](protocol.proto). Its standalone entry point serves this API;
HTTP is limited to a health probe. The integration app retains its browser-facing HTTP API.
There is no transparent runner `Attach` tunnel or caller-supplied runner URL.

**Status:** gRPC server/client implementation and acceptance tests are being added in #8744.
Production app cutover and deployment are not complete. The earlier `api.py` HTTP adapter and
its native tests remain transitional test coverage, not a second deployed service contract.

## Authentication and destinations

Every RPC requires one `authorization: Bearer …` metadata value. The shared workload-principal
resolver performs TokenReview for the configured audience and allowed ServiceAccount namespaces.
Missing, invalid, duplicate, or revoked credentials are refused. The Python client rereads its
projected token file on every RPC, including follow reconnects.

A `SandboxDestination` contains the owner ServiceAccount (namespace/name), Sandbox name, and
Sandbox UID. A `SessionDestination` wraps that destination and adds an explicit runner session ID.
The owner is a resource selector, not a forwarded identity. Ordinary callers can address only their
own account. `trusted_accounts` grants selected service accounts cross-owner access; it defaults to
empty. All sessions under an account share the sandbox trust boundary. There is no inferred Thread.

Resolution checks the stored Sandbox account, UID, lifecycle state, and current ready Pod's controller
ownership before selecting its endpoint. Name reuse with a new UID is refused. A successor Pod under
the same Sandbox may replace the endpoint. These are Kubernetes association checks, not cryptographic
runner authentication. **TODO:** proper runner RPC authentication/TLS; v1 requires network isolation.
Service API authentication is implemented independently of that deferred runner-authentication work.

## Inventory and explicit sandbox lifecycle

These unary RPCs require an account in **both** `manager_accounts` and `trusted_accounts`, and an
enabled provisioning backend:

- `ListSandboxes`, `GetSandbox`: Kubernetes-backed inventory, including concrete stored launch
  bindings, provisioning state, and current Pod observations.
- `ListTemplates`, `ListKubernetesGrants`: concrete backend choices, not app UI presets.
- `CreateSandbox`: concrete template, policy/grant selections, optional session defaults, and bootstrap.
  Grant intent is stored on the Sandbox so reconciliation can recover partial provisioning without
  the app. The RPC returns after provisioning orchestration, not necessarily after Pod readiness.
- `SuspendSandbox`, `ResumeSandbox`, `DeleteSandbox`: explicit owner/name/UID-pinned mutations.
  Resume refuses incomplete provisioning; deletion requires suspension.

Create is **not currently idempotent**. After a timeout or lost response, reconcile inventory rather
than blindly retrying. The client disables gRPC retries and adds no application retry loop. Existing
Kubernetes ownership labels, stored bindings, identities, and PVC policy remain unchanged.

## Sessions and commands

- `ListSessions`: Sandbox destination; returns native retained `SessionSummary` messages.
- `InspectSession`: session destination; returns a native `Attached` snapshot. Does not create or resume.
- `InitializeSandbox`: executes the backend-configured bootstrap through the runner. Exact retries use
  the runner's stored bootstrap result; no caller-supplied bootstrap override in this RPC.
- `OpenSession`: explicit session creation/start using stored defaults plus selected overrides. Bootstrap
  and setup use the runner's existing idempotence; the response is the native attachment snapshot, not
  a claim that all setup or a model turn has completed.
- `ResumeSession`: uses exactly the runner-retained spec, without applying today's defaults/instructions
  or rerunning setup. Missing sessions and failed/interrupted setup are refused.
- `SubmitCommand`: forwards an unchanged common-protocol `Command` only to a running harness and returns
  the original `EventEntry` containing its exact matching `CommandAdmitted`. Specify a native `Follow`
  cursor before the possible admission when reconciling an uncertain submission.

Initialize/open/resume require `manager_accounts`. Cross-owner management also requires
`trusted_accounts`; neither list implies the other. Delivery-only trusted accounts do not gain launch
permission. This is a service lifecycle boundary, not fine-grained command RBAC inside the runner.
Read/follow/command RPCs never provision, resume, or wake a Sandbox or harness.

### Launch overrides and field presence

`OpenSessionRequest.spec` is the existing runner `SessionSpec`. Its `override_mask` names the exact
proto fields to replace in stored defaults, including fields explicitly set to empty/default values.
For example, `paths: ["model", "instructions"]` selects `spec.model` and `spec.instructions`; an empty
instructions string clears the caller's inherited instructions, but not backend platform guidance.
Nested paths, unknown paths, duplicate paths, and supplied nondefault fields outside the mask are
refused. An empty mask means no overrides. Optional `setup_script` distinguishes omitted from empty.

The backend adds operational guidance and the explicit destination. When management is enabled,
configure the egress/Actions URLs for bundled instructions or explicitly configure `agent_instructions`.
Stored specs are never rewritten. Changed defaults may make an Open retry conflict: inspect retained
state and explicitly resume rather than silently adopting a different spec or creating another ID.

Resume also needs the native harness's retained conversation. The pinned Claude harness can refuse
resuming an empty conversation that never persisted a turn. The service surfaces that refusal; it does
not fabricate native history or claim runner admission proves native persistence.

## Event following

`FollowSession` is server-streaming. Its request selects an explicit session and a native `Follow`
cursor. It emits:

1. One native `Attached` snapshot.
2. Original `EventEntry` messages, preserving serving-log cursor, source origin, and command correlation.
3. An `ended` observation only when the native runner attachment reaches successful EOF. This is a
   transport observation, not a synthesized execution Event or deletion of retained history.

A bounded follow lease ends with `DEADLINE_EXCEEDED`; backend transport failure is `UNAVAILABLE`.
Neither is native closure. Bare service-stream EOF without `ended` is an error in the client, not
session termination. Reconnect from the last fully consumed/committed cursor; each reconnect checks
identity and destination again. Follow flow-control stalls are inside the lease deadline, and every
exit cancels the runner attachment and closes its channel. There is no unbounded fan-out queue.

The service retains no additional session-log archive. Runner logs are durable on the state volume,
but reading them requires a reachable runner. Clients needing retention independent of that volume
must archive events themselves. The app keeps its existing PostgreSQL archive and checkpoints as a
client of service event following; migrating that archive is not a required follow-up.

## Errors and uncertain outcomes

- `UNAUTHENTICATED`: invalid workload bearer.
- `PERMISSION_DENIED`: unauthorized destination or management operation.
- `NOT_FOUND`: missing/stale Sandbox incarnation.
- `INVALID_ARGUMENT`: malformed request or invalid concrete grant selection.
- `FAILED_PRECONDITION`: runner or Sandbox state refuses the operation.
- `UNAVAILABLE`: destination/backend unavailable; no offline admission.
- `DEADLINE_EXCEEDED`: operation deadline or follow lease expired.

Neither a successful write nor a timeout proves admission/rejection. A mutation may commit before
its response is lost. Reconcile commands with the unchanged ID/payload and runner evidence; admission
is neither harness consumption nor command completion nor inbox acknowledgement. No service command
queue, new receipt authority, or exactly-once guarantee is introduced.

## Server configuration and cutover

`//agentplane/sandbox_service:server` uses `AGENTPLANE_SANDBOX_SERVICE_*` environment variables or
kebab-case CLI flags. Required settings are `sandbox_namespace` and
`allowed_service_account_namespaces`. `token_audience` defaults to the existing `agentplane-egress`
workload audience. Kubernetes access is in-cluster unless `kubeconfig` is supplied.

`port` defaults to 8080 for gRPC. `health_port` defaults to 8081 for unauthenticated HTTP `/healthz`;
it is liveness, not proof that Kubernetes or a particular destination is ready. Admission requests
are bounded by `admission_timeout_s` (default 15); management by `lifecycle_timeout_s` (default 300);
follow leases by `follow_lease_s` (default 30, configured maximum 60).

Deployment must grant the service the appropriate Kubernetes/TokenReview/provisioning permissions,
project an audience-correct token for app-to-service calls, and enforce sole normal production access
to runner control/event RPCs. Do not leave a direct-runner app fallback or two provisioning reconcilers.
Inventory/backup and rollback checks gate staging handoff; no staging data reset is part of this change.
