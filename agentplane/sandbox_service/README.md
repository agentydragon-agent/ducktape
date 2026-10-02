# Sandbox Service

Independent backend owner for sandbox lifecycle and runner session access.
The [plan](../plans/sandbox_service.md) describes the intended service; the
[service dependency rule](../docs/service_boundaries.md) applies to this package.

## Implemented foundation

`command_relay.admit_running_command` extracts the existing app's running-session
command relay. The app now uses it while retaining its existing archive wait and
error mapping. The helper:

- Opens an explicit runner session without a spec, so it cannot create or resume it.
- Sends the caller's unchanged common-protocol `Command` and requests detach.
- Waits for the runner's exact `CommandAdmitted` and returns its original `EventEntry`.
- Cancels the attachment on every exit, without taking ownership of the client.

Admission is not native user-message confirmation, model completion, or inbox
acknowledgement. An uncertain result needs reconciliation against the runner journal
with the same command ID/payload and an appropriate runner-log replay cursor. This
helper adds no retry, command queue, Event authority, or exactly-once guarantee.

Protocol-edge tests use a controllable gRPC peer. Native tests exercise both harnesses
with scripted model endpoints, without the integration app or its database. They cover
admission before model completion, receipt replay, and refusing to create/resume a session.

## Inventory and concrete launch configuration

`inventory.py` now owns the existing Kubernetes-backed inventory and low-level
Sandbox lifecycle operations. `session_config.py` owns the concrete, serialized
launch fields; `kubernetes_grants.py` owns the selected grant shapes. The app imports
these implementations. UI preset catalogs remain app-owned and are not interpreted
by this package. Existing annotation keys, field/class names, defaults, ServiceAccount
creation, PVC policy, and provisioning behavior are unchanged.

`provisioning.py` owns recoverable grant orchestration and policy binding, with pending launch
intent stored on the Sandbox. Switching production callers and reconciler ownership to the
separately deployed service is still in progress; the package extraction alone is not a cutover.

## Session API

The [authenticated gRPC API](API.md) has a standalone server entry point and Python client. It resolves
SA-authorized, UID-pinned destinations inside the configured Kubernetes inventory, then
inspects, commands, or follows existing runner sessions. Separately authorized explicit
management routes list sessions, bootstrap, open, and resume using runner-retained specs.
The backend owns launch instructions and concrete defaults; no UI preset lookup is needed.
Read/command/follow never start sessions. Separate explicit Sandbox lifecycle operations can resume
a Sandbox. Read/follow availability is limited to the surviving runner log.

## Still to extract

This is **not yet a deployed service or a completed app cutover**. The agreed service API is
protobuf/gRPC; the standalone server serves it, not the earlier HTTP adapter. The latter remains
transitional test coverage, not a parallel deployed API. The low-level relay still requires an already selected/authorized client; the service
API provides that boundary. Full test migration, app callers, and deployment/authority handoff remain
in the [extraction plan](../plans/sandbox_service.md). Notifications must not work around these gaps
by depending on the app.

The service will not own a session-log archive. Runner logs are durable on the state volume; clients
needing independent retention must archive events themselves. The app keeps its existing PostgreSQL
archive and checkpoints. Archive migration is not a required follow-up.

TODO: proper runner RPC authentication/TLS. The planned v1 service-to-runner connection
reuses the current network trust boundary; this helper does not confer identity or
permission, and it does not introduce runner command RBAC.

This extraction changes no database schema, stored wire format, deployment, or staging
resources. Subsequent storage/ownership cutovers must inventory and preserve existing
staging data, with a backup/restore and migration plan before making changes. Ask before
any destructive reset, unavoidable loss, or disruptive/identity-breaking cutover.
