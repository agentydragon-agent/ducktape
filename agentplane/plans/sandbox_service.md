# Sandbox Service extraction

Status: **planned, not implemented.** This is the concrete backend boundary required by the
[service dependency rule](../docs/service_boundaries.md). The integration app must be a client;
notifications must not start with an app API, app-owned table, or app-issued Thread ticket dependency.

## Purpose and ownership

The Sandbox Service provisions/manages sandboxes and provides authorized access to their runner
sessions. This is more than a directory: reaching a session, determining its lifecycle state, deciding
who may control/read it, and eventually bringing it online are related backend responsibilities.

The notification service remains separate. It decides which source events match subscriptions and
persists payloads/inbox state; it asks the Sandbox Service to deliver a notice. Runners do not dial
notifications, and notifications does not acquire its own parallel provisioning/runner-control path.

The Sandbox Service owns:

- Sandbox provisioning and suspend/resume/removal operations as extracted from the app.
- Trusted mapping from an explicit destination to its provisioned sandbox and runner session, current
  endpoint, ServiceAccount authority, and lifecycle state.
- Authentication/authorization of callers at its API, distinct from direct runner network access.
- Forwarding commands and exposing runner admission/effect receipts and replayable event following.
- Session creation/configuration and backend-required instructions/context for extracted launch paths,
  so neither automated agents nor services require the integration app to prepare their sessions.
- Backend event archival/ingestion as it is moved from the app, with one declared archival owner.

It does not own notification provider payloads, inbox acknowledgement/reminder policy, Action
Decisions/execution, native harness scheduling, browser sessions, or UI-only Thread projections.
Product Thread annotations can remain in the app without becoming a backend routing dependency.

## Minimum slice before notification v1

Extract the smallest coherent backend that supports:

1. **Inspect an explicit destination:** validated destination/account/session binding and current
   lifecycle/availability. Session IDs remain explicit; do not infer an app Thread from a workload.
2. **Submit a command to a running session:** use the existing immutable runner `Command` and stable
   ID. A response indicating forwarding is not admission, and admission is not harness confirmation.
3. **Read/replay/follow session events:** authorize the selected session, preserve runner origin and
   command correlation, and expose reconnect cursors scoped to the serving log.
4. **Independently establish/manage the destinations required by the slice:** move the relevant
   provisioning, session creation, prompt/context assembly, and discovery dependencies out of the app.
   No hidden requirement that the UI ran once to bootstrap the new service's state.

These describe operations, not a selected REST/gRPC schema. Notifications and the app use the same
backend contracts. Each request is authenticated and authorized against its destination. Shared SA
identity remains the ordinary agent authority; a caller-supplied SA or destination ID is not proof of
access. For trusted service calls, specify the delegated resource-owner context and configured service
permissions rather than treating arbitrary forwarded identity headers as authentication.

Read access, command/control access, and permission to wake a destination are distinct decisions.
Trusted services may receive broad access initially; this does not require new command-level RBAC
inside the runner. Reading a log must never provision or resume a sandbox as a side effect.

## Command and notification flow

1. Notifications authenticates the agent and creates an SA-authorized subscription with an explicit,
   verified destination. The Action provider separately establishes authorized source access.
2. It durably stores matching notification payloads and a service-authored inbox notice with a stable
   command ID and covered inbox range.
3. It submits that command through the Sandbox Service with **no wake allowed in v1**.
4. The Sandbox Service validates the destination/access, resolves its runner internally, and forwards
   the command to the existing session without implicitly creating or resuming it.
5. Notifications follows the command's runner Events through the Sandbox Service and records admission,
   `HarnessUserMessageConfirmed`, or failure/no-op. Receipt replay handles reconnect without new IDs.
6. The agent reads payloads and explicitly advances the inbox HWM. That acknowledgement is unrelated
   to the command's admission/confirmation and stays entirely notification-service-owned.

For an unavailable destination, report unavailability and leave the notification pending under its
retention policy. Do not imply durable acceptance of an offline runner command by the Sandbox Service.
A connection loss around forwarding still requires reconciliation against the runner's journal; a
relay does not remove the existing native-effect crash window or create an exactly-once guarantee.

## Event following and archive ownership

Fan-out is a useful responsibility here: one or more backend attachments can serve multiple authorized
readers, including the UI and notification receipt tracking. Use shared ingestion/attachment machinery
where useful, but preserve the existing independent runner attachment semantics and per-reader cursors.
Bound slow consumers and recheck authorization for long-lived follows according to the selected policy.

The runner authors execution facts. A relay or archive preserves Event origin, ordering, raw native
provenance, and causal command IDs; it must not synthesize a duplicate successful execution event or
make transport acknowledgement look like harness consumption. Serving-log cursors and original source
identity remain distinct when history is copied.

Choose the archive cut explicitly:

- If the initial API only follows the surviving runner log, state that availability boundary clearly.
  Do not fall back to app-owned PostgreSQL when the runner is gone.
- If backend consumers need archived history independent of the runner, move the existing archival/
  ingestion responsibility and required ownership records out of the app. Preserve retained history;
  do not add another independent event store or make both services authorities for the same archive.
- App-specific folds and browser projections may remain app-owned clients of the backend event source.

Resolving this ownership is part of extraction; moving the entire hosted product Thread model is not
an automatic prerequisite for the minimum session-scoped API.

## Discovery and access implementation

Kubernetes already holds hosted sandbox/Pod inventory. Extract the narrow endpoint/account/lifetime
lookup code internally into the Sandbox Service (using shared Kubernetes helpers as appropriate), not
into another directory deployment. See [discovery and access notes](runner_discovery.md). Do not add a
runner registration callback, raw agent-supplied connection URL, or independent runner identity issuer.

V1 reuses Cilium-controlled access to the existing runner RPCs. After the extracted-path cutover,
Sandbox Service is the control-plane caller for those paths; app and notifications call its API rather
than keeping a second direct runner route. Audit intentional administrative/test clients and overlapping
policies. Authenticate the Sandbox Service's public/service API using existing workload/operator
foundations; deferring runner RPC authentication does not make this new API unauthenticated.

**TODO after v1:** proper authentication and transport security on runner connections, consistently
for all legitimate runner clients. No JWT issuer, app-issued ticket, or fine-grained runner RBAC is a
v1 prerequisite. Network reachability control must not be described as cryptographic RPC auth.

## Extraction sequence

1. Identify the minimal ownership cut in app inventory/provisioning, session/command bridge, prompt
   construction, and event ingestion/following. Record archive ownership and required state moves.
2. Extract the Sandbox Service with independent configuration, persistence where needed, and API
   authorization. No imports of app implementation, app-table reads, or app process/bootstrap dependency.
3. Migrate the app to consume the extracted APIs for those paths. Avoid competing provisioning/control
   authorities or a permanent direct-runner bypass of the service's authorization boundary.
4. Implement notification v1 against Sandbox Service and Action Service. Keep no-wake behavior,
   persisted payloads, explicit inbox HWM, no reminders, and existing runner evidence semantics.
5. Prove the extracted paths and notification flow with the app stopped, including backend restart,
   destination setup without UI bootstrap, replay/recovery, and authorization denial.

The minimum extraction gates notification v1. Further provisioning/UI refactors can be staged by
operation, but a newly extracted backend operation may never depend on an app-owned fallback.

## Later, not implied by extraction

- Notification-triggered wake: separately authorize requesting sandbox/harness resume and budget it,
  then deliver through the same session interface once ready. Notifications does not become a lifecycle
  manager; a suspended local process is not expected to wake itself.
- Durable admission of commands for offline destinations: an explicit product/queue decision, not a
  consequence of adding a resume API. Keep runner journal ownership and successor-session replay honest.
- Proper runner authentication/transport security, external runners, cross-cluster routing, and product
  Thread continuity across successor sessions. None warrants a v1 reverse dependency on the app.
