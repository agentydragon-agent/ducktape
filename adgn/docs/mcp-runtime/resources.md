# Resources Server (Dedicated)

A dedicated MCP server that exposes resource operations as tools for agents/LLMs and centralizes subscription management. It complements the Compositor:

- Compositor (aggregator): mounts child servers and provides the aggregated protocol surface. Clients use it for direct `resources/list` and `resources/read` over the protocol.
- Resources server: provides tool-callable list/read for LLMs, plus subscribe/unsubscribe and a single subscriptions index resource for observability. It does not duplicate Compositor internals or protocol resource plumbing.

## Scope

- Tools: list and read (tool-callable surfaces) for LLMs
  - `list(server?, uri_prefix?) -> {resources:[...]}`
  - `read(server, uri, start_offset?, max_bytes?) -> {window, parts, total_parts}` (windowed helper for large content)
- Subscribe/unsubscribe tools: `resources/subscribe`, `resources/unsubscribe`
- List-changed selection tools: `subscribe_list_changes({server})`, `unsubscribe_list_changes({server})`
- Aggregates/proxies operations across mounted servers via the Compositor
- Forwards raw notifications; no watermark/HWM/coalescing logic
- Subscriptions index resource: `resources://subscriptions` (single canonical index)
- TODO: `list_resource_templates(server?)` tool for parity with the protocol template listing

Out of scope
- Approvals/policy (Compositor policy middleware on tools/call)
- Tool prompts and tool calls (other servers)
- Watermarks/HWMs and coalescing (agent/orchestrator concern)

## Responsibilities

- `resources/list`: return the union of resources from mounted servers (namespaced by server as per Compositor rules).
- `resources/read`: fetch content for a URI (no protocol‑level windowing; callers may implement windowing in higher layers).
- `resources/subscribe` / `resources/unsubscribe`: manage subscriptions for the calling principal; emit raw `resources/updated` on changes at origin.
- Persist subscriptions in SQLite: `subscriptions(server, uri, pinned, added_at)`.
- Expose active subscriptions back to clients (see below).

Compositor metadata (introspection)
- Exposed via a dedicated server `compositor_meta` mounted under the Compositor.
- Per‑server state resource (implemented):
  - `resource://compositor_meta/state/{server}` (typed JSON):
    - `{state: "initializing"}` | `{state: "running", initialize: <InitializeResult>, tools: [...]}` | `{state: "failed", error}`.
  - No dedicated mounts index; enumerate `resource://compositor_meta/state/{server}` via `resources/list` and watch `resources/list_changed` for attach/detach.
  - Instructions/capabilities are available via the InitializeResult returned in the running state; no separate resources are exposed.
Status: implemented per‑server state; clients compose a mounts map by listing state resources.

## Exposing Active Subscriptions

- Synthetic resource: `resources://subscriptions` (implemented)
  - JSON body example:
    ```json
    { "subscriptions": [
      { "server": "ui", "uri": "ui://chat/inbox", "pinned": true, "added_at": "2025-10-09T12:34:56Z" },
      { "server": "matrix", "uri": "matrix://room/!abc/last", "pinned": false, "added_at": "2025-10-09T12:40:00Z" }
    ]}
    ```
  - Listed by `resources/list`, readable via `resources/read`, subscribable; emits `resources/updated` when the set changes.
  - Includes `list_subscriptions` (array; can contain multiple origins) reflecting the selected origins for `resources/list_changed` interest. Example:
    ```json
    { "subscriptions": [...], "list_subscriptions": [ { "server": "origin", "present": true, "active": true } ] }
    ```

Note: we do not expose per-server “list subscriptions”. The single index is the UI/model surface.

Pinned entries
- Attempting to unsubscribe a pinned subscription returns a structured `forbidden` error.

List-changed subscriptions
- Multiple origins may be selected concurrently. Each `subscribe_list_changes({server})` call adds that origin to the selection; `unsubscribe_list_changes({server})` removes it.
- The server reflects compositor `resources/list_changed` events and emits `resources/updated` for `resources://subscriptions` whenever any subscribed origin fires.

## Notifications

- Raw notifications only:
  - Forwards origin `notifications/resources/updated` and `notifications/resources/list_changed` as received.
  - No coalescing or watermark logic is applied here.

## Routing & Security

- Mounted under the Compositor as server `resources`.
- Clients (agent, container, human UI) access it through the Compositor endpoint; do not expose the resources server directly.
- Authentication/authorization is enforced at the Compositor boundary; the resources server may rely on caller identity passed by the Compositor for per‑principal subscriptions.

## Notes

- MCP spec defines no windowing for `resources/read`. If large reads are needed, provide higher‑level helpers outside this server (e.g., SDK adapter functions) that slice content for UI/model friendliness.
- Watermarks/HWMs and any coalescing used to build model inputs are maintained by the orchestrator/handlers, not by this server.
