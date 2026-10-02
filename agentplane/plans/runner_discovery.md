# Shared runner discovery and v1 access control

Status: **implementation plan, not a shipped extraction or policy change.** This supersedes the
separate runner-directory service proposed in PR #8730. Hosted runners already belong to provisioned
sandboxes and their Pod incarnations; Kubernetes is the inventory. Extract reusable discovery code,
not another deployment, registration protocol, database, or identity issuer.

## Responsibilities

Keep three concepts separate:

- **Authority:** the authenticated ServiceAccount controls access to notification resources. Workloads
  sharing an account have the same authority; no per-session caller credentials are required.
- **Conversation:** the caller explicitly identifies the runner session. No implicit current-session
  discovery or integration-app Thread lookup.
- **Delivery binding:** an existing provisioned runtime reference identifies where that session lives.
  Discovery resolves its current endpoint. It does not grant a caller authority over that destination.

The [notification service](notifications.md) remains independent of the integration app. Both services
can observe the same authoritative Kubernetes resources through shared discovery code. Separate caches
are not competing registries; neither client invents ownership or treats stale observations as deletion.

Existing code to extract from:

- [`SandboxInventory`](../app/inventory.py) and [`LiveIndex`](../app/live.py) observe managed Sandbox
  and Pod resources, including configured ServiceAccounts, immutable UIDs, and current addresses.
- [`Runners`](../app/agent_runtime/runner/runners.py) resolves that inventory to runner clients.
- [`EventLogStore.runner_session`](../app/agent_runtime/events/event_log.py) maps app Thread IDs to
  runner sessions. That mapping stays app-owned; notification routing does not need it.

Do not move all provisioning, app views, or Kubernetes management into a generic library. Extract
only the runner endpoint/account/lifetime projection and the bounded lookup/watch machinery it needs.
Reuse the existing Kubernetes list/watch primitives. Each consuming service gets only the Kubernetes
read permissions required for its configured hosted inventory, not arbitrary cluster discovery.

## Proposed library seam

The conceptual operation is `resolve_runner(destination_ref)`, returning the current runner endpoint
and configured ServiceAccount, temporary unavailability, or authoritative permanent removal. A lookup
failure is an error, not any of those lifecycle facts. Final Python types/names are not prescribed here.

`destination_ref` names an existing provisioned sandbox/runtime with its immutable UID and the lookup
coordinates needed to find it. It is not a new directory-owned `runner_id` or a caller-supplied URL.
Normal Pod replacement retaining runner storage changes the endpoint, not the bound destination.
Reused resource names/IPs must not redirect subscriptions. Discarding/replacing session storage needs
an explicit generation/removal rule; matching runtime/session names alone cannot prove continuity.

For the usual self-notification request, the delivery binding can be established from the authenticated
workload's Pod and trusted provisioning associations. This is routing, not a new workload-to-sandbox
ownership test replacing SA authorization. If the API allows an explicitly supplied destination,
verify its configured ServiceAccount against the caller's authority. Persist the verified delivery
binding; do not keep guessing among runners with matching session IDs.

A runner session ID is only unique within its retained state. Settle whether the public notification
scope qualifies `session_id` with `destination_ref`, or guarantees uniqueness within the owner SA and
rejects conflicting bindings. The proposed examples use explicit qualification, supplied in agent
context. Neither option needs a separate registry or a server-selected "current" session.

Do not accept an arbitrary callback target or infer a trusted binding from an unverified label/name.
A retired UID must not resolve to a newly created object with the same name. A missing endpoint, watch
failure, or timeout is not proof of permanent removal. App Thread archiving is not runtime retirement.
The runtime/session cleanup and storage-replacement rules remain implementation details to settle.

## Existing app-to-runner access boundary

The checked-in app client uses `grpc.aio.insecure_channel` in
[`RunnerClient`](../runner/client.py), and the runner server uses `add_insecure_port` in
[`service.py`](../runner/service.py). There is no bearer metadata or application-level RPC identity
verification on that path. The loopback default for local use is not the hosted deployment's bind:
[`cluster/cdk8s/agentplane/app.py`](../../cluster/cdk8s/agentplane/app.py) starts it on `0.0.0.0:7000`.

Cilium network policy currently supplies the hosted access boundary:

- App egress explicitly permits runner Pods on TCP 7000.
- Runner ingress permits Pods in the same namespace on that port, not just the integration app.
- Whether a different workload can connect also depends on its egress and all applicable policies.

These are checked-in source facts, not a claim of live enforcement verification. Network reachability
control is not cryptographic caller authentication, and an insecure gRPC channel does not provide TLS.
Do not describe this path as JWT-authenticated or mTLS-protected.

## V1: reuse and tighten network-policy access

Make notifications another trusted control-plane runner client, using the existing mechanism:

1. Permit notification-service egress to the hosted runner endpoints on TCP 7000.
2. Narrow runner ingress to the intended integration-app and notification-service identities, plus
   explicitly audited test/administrative clients. Prefer namespace-qualified Cilium ServiceAccount
   identity selectors where supported, not labels ordinary sandbox workloads can assign themselves.
3. Audit the union of ingress/egress policies. Adding a narrow rule while leaving a broad allow in
   another policy does not tighten access. Verify source selection and network behavior in acceptance.
4. Keep the runner RPCs and attachment semantics unchanged. Network-authorized clients retain full
   protocol/history access; do not introduce per-command RBAC or receipt-only streams for notifications.

This trusts the notification service as a control-plane component with network access to the configured
runner set. The runner does not verify a per-session capability. The service must still enforce caller
SA ownership and destination binding on its agent-facing API; a caller never chooses a raw endpoint.
Not interrupting, changing models, or resuming harnesses is notification-service behavior, not an RPC
permission enforced against this trusted client.

Delivery resolves the bound destination, connects directly using the existing runner client, and opens
an existing session without a spec. `Attached` confirms current harness state; a routable endpoint is
not proof that the harness is running. Persist notice identities and reconcile receipts as described
in the notification plan. No app proxy, runner-to-notification callback, directory service, or token
issuer is required for this v1 path.

## TODO: proper runner authentication and transport security

**Deferred follow-up, not a notification-v1 prerequisite.** Add proper service-to-runner authentication
and transport security consistently for both the integration app and notification service. Do not
build a notification-specific credential system or assume network policy is equivalent to RPC auth.

The follow-up must choose and test:

- Authenticated caller identity and runner peer identity over protected transport; mTLS or tokens over
  TLS are candidates, not selected mechanisms. JWT issuance is not part of v1.
- Provisioning of trust/credentials, rotation/revocation, and expiry for long-lived attachments.
- Behavior across Pod/endpoint replacement, including rejection of wrong peers and stale credentials.
- One shared client/server integration for all runner consumers, with network policy retained as an
  additional boundary. Fine-grained command-level RBAC remains outside this notification feature.

Until then, the documented boundary is Cilium-enforced control-plane access to the existing unauthenticated
RPC protocol. Do not claim this TODO is implemented merely because positive connectivity tests pass.

## Implementation and acceptance

1. Extract shared hosted-runner discovery from the app without introducing another authoritative
   registry. Migrate the app and use the same library in notifications. Preserve discovery health/error
   reporting; settle immutable runtime/storage binding and explicit session qualification.
2. Implement the v1 network-policy changes and audit existing callers. Verify app and notifications
   can connect, but ordinary sandbox workloads and an unrelated same-namespace workload cannot.
   Exercise both source egress and destination ingress, including overlapping allow rules.
3. Prove session attachment and receipt recovery across an endpoint change with retained state; reject
   stale UID/name reuse and conflicting session bindings. Never create a session as a lookup side effect.
4. Verify stopped harnesses are not resumed. Temporary absence preserves subscriptions/inboxes;
   authoritative removal follows explicit cleanup rules rather than connection-failure heuristics.
5. Verify notifications works without app Thread lookup, the app process, or any runner callback to it.

A separate directory API, external-runner registration, or cross-cluster discovery can be revisited
when a concrete consumer cannot use the hosted inventory. They are not v1 requirements.
