# TODO: MCP resource change subscriptions (push notifications)

Status: Missing in current FastMCP Python SDK; desirable for reactive PE/agents.

## Why we want this
- Reactive UX: When a server-side resource (e.g., container.info, test results, file snapshots) changes, clients should be notified without polling.
- Lower latency and cost: Avoid repeated list/read cycles for resources.
- Cleaner agent loops: Agents can respond to server events instead of guessing/polling.

## Current state (our env / SDK)
- FastMCP Python (installed version) exposes tools, prompts, resources, but does NOT provide a public API to:
  - register server-side notifications (no `@notification` decorator)
  - declare or emit resource list/content change notifications
- The MCP types include capability flags (e.g., `resources.subscribe`, `resources.listChanged`) and generic JSON‑RPC notification types, but FastMCP’s server layer does not surface a simple way to send resource change notifications to the client.

## Workarounds we’re using now
- Dynamic resources: compute content on read; clients poll via `resources/read` when they need updates.
- Tool-mediated state updates: clients call a tool to update state, then re‑read resources.

## Desired design (when SDK supports it)
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
- Optional: per‑URI content update notifications delivered as `notifications/resources/updated` with `{uri}` payload.
- Capabilities reflect availability; clients can feature-detect.

## Migration plan (once available)
1) Detect SDK support; gate feature via InitializeResult.capabilities.
2) Add subscription in McpManager on open (if supported), wire MiniCodex to set a notification handler.
3) Update runtime flows to react to notifications (e.g., refresh banners, invalidate caches).
4) Add tests: subscribe → server mutates resource → notification arrives → client re‑reads and validates new content.

## Tracking
- Blocked by SDK surface (Python): no public notification API in FastMCP for resources.
- Candidates to explore upstream:
  - Expose `@notification` decorator in FastMCP
  - Add ResourceManager hooks + server notification helpers

## Links
- In-proc transport design: `src/adgn_llm/mcp/inproc_transport_design.md`
- Prompt Engineer MCP client design: `src/adgn_llm/inop/prompt_engineer_mcp_client_design.md`
