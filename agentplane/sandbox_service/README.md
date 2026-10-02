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

The app still orchestrates grant reconciliation and policy binding, and still calls
these Python components in-process. Moving that orchestration and switching callers
to a separately deployed API are subsequent cuts, not accomplished by this move.

## Still to extract

This is **not yet a deployed service or an authenticated public API**. Callers must
select and authorize the destination before using the relay. Destination discovery,
API authentication/authorization, provisioning/lifecycle, session configuration and
backend prompt assembly, event following/fan-out, and deliberate archive ownership
remain in the [extraction plan](../plans/sandbox_service.md). Notifications must not
work around these gaps by depending on the app.

TODO: proper runner RPC authentication/TLS. The planned v1 service-to-runner connection
reuses the current network trust boundary; this helper does not confer identity or
permission, and it does not introduce runner command RBAC.

This extraction changes no database schema, stored wire format, deployment, or staging
resources. Subsequent storage/ownership cutovers must inventory and preserve existing
staging data, with a backup/restore and migration plan before making changes. Ask before
any destructive reset, unavoidable loss, or disruptive/identity-breaking cutover.
