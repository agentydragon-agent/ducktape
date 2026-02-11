# MCP resource change subscriptions (push notifications)

Status: Implemented in ADGN via NotifyingFastMCP and server hooks; upstream FastMCP Python still lacks a formal public notification API, so we extend/wrap it internally.

## Why we want this
- Reactive UX: When a server-side resource (e.g., container.info, test results, file snapshots) changes, clients should be notified without polling.
- Lower latency and cost: Avoid repeated list/read cycles for resources.
- Cleaner agent loops: Agents can respond to server events instead of guessing/polling.

## Current state (our env / SDK)
- Upstream FastMCP Python does not expose a public `@notification` decorator or helpers to emit resource notifications.
- ADGN provides `NotifyingFastMCP` which captures sessions and exposes:
  - `broadcast_resource_updated(uri)` and
  - `broadcast_resource_list_changed()`
  These are used by in-proc servers to push resource notifications to clients.
- The Compositor captures child `resources/list_changed` via a message handler and exposes a hook `add_list_changed_listener(cb)` for in-proc servers to react.

## What we’ve built
- `resources` server:
  - Tools: `list`, `read`, `subscribe`, `unsubscribe`.
  - List-changed interest: `subscribe_list_changes({server})`, `unsubscribe_list_changes({server})` (multi-origin).
  - Synthetic index resource `resources://subscriptions` includes both per-resource subscriptions and `list_subscriptions` (origins selected for list-changed). The server emits `ResourceUpdated` for the index when selection changes or a subscribed origin fires `list_changed`.
- `compositor_meta` server:
  - Emits `ResourceListChanged` on mount lifecycle changes and `ResourceUpdated` for per-server state resources.
- Agent runtime:
  - Notification buffer groups `ResourceUpdated` and `ResourceListChanged` for reducers/UI, using compositor attribution.

## Desired design (upstream SDK)
- Server capabilities
  - `resources.subscribe: true` and `resources.listChanged: true` in InitializeResult.capabilities.
  - Optional `resources/updated` notifications keyed by URI (content change), and `resources/listChanged` when the index of resources changes.
- Client API
  - `ClientSession.subscribe_resources(uris: list[str] | None)` → request notifications for either specific URIs or all.
  - `ClientSession.on_notification(handler)` or typed handlers to receive updates (listChanged, updated).
- FastMCP server API
  - `fastmcp.subscribe_resources(handler)` to register subscription requests.
  - `fastmcp.notify_resource_updated(uri)` and `fastmcp.notify_resources_list_changed()` helpers to send JSON‑RPC notifications.

## Acceptance criteria
- Server can emit at least `notifications/resources/listChanged`; client receives it without polling.
- Per‑URI content update notifications delivered as `notifications/resources/updated` with `{uri}` payload (supported via NotifyingFastMCP; used for index updates).
- Capabilities reflect availability; clients can feature‑detect.

## Remaining work / follow-ups
1) Persistence for subscriptions (SQLite) so selections survive restart.
2) Optional per-subscription resources (e.g., `resources://subscriptions/{server}`) for finer‑grained list_changed tracking.
3) Consider emitting `ResourceListChanged` from the resources server itself when subscribed origins fire, in addition to index `ResourceUpdated` (currently adequate via index updates).
4) Capability surfacing for list-changed support in InitializeResult where relevant.

## Tracking
- Upstream FastMCP: propose `@notification` decorator and resource notification helpers.

## Links
- In-proc transport design: `src/adgn/mcp/inproc_transport_design.md`
- Prompt Engineer MCP client design: `src/adgn/inop/prompt_engineer_mcp_client_design.md`
