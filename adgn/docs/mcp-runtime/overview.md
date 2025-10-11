# mcp runtime v2: structured overview (sync first, async later)



> This document reorganizes and consolidates the current design into a clear, implementation‑oriented flow. It links out to focused docs (<ui-chat.md>, <matrix.md>, <control.md>, <resources.md>), and calls out open questions. V1 covers in‑proc sync execution; later sections outline optional chat resource mode and minimal async needed for container‑initiated calls. See also <../vision.md> for the high‑level philosophy and goals.

## Table of Contents
- Executive Summary
- Architecture At A Glance
- Modes & Phasing
- Naming & Routing
- Approvals (Authoritative in Compositor)
- Turn Orchestration (Sync)
- UI Chat (Summary; link to ui-chat.md)
- Loop Control (Summary; link to loop-control.md)
- Minimal Async for Container‑Initiated MCP Calls
- Transports & Security
- Persistence & State
- Operational Guarantees
- Testing & Rollout
- Appendices (Errors; MCP protocol notes)
- Open Questions & Follow‑Ups

---

## Executive Summary

- The runtime is built around three parts:
  - Agent (MiniCodex) — runs turns; handlers shape loop control and injections.
  - Compositor (FastMCP) with embedded policy middleware — aggregates MCP servers via proxy mounts and enforces approvals as a pre‑dispatch filter on `tools/call`.
  - Resources server (dedicated) — centralizes `resources/list`, `resources/read`, and `resources.subscribe/unsubscribe`, persists subscriptions, and forwards raw notifications (no watermark/HWM or coalescing semantics).
- V1 (sync):
  - All tool calls from the model are gated synchronously inside the Compositor by the policy middleware; denials return JSON‑RPC errors.
  - Yielding is explicit via an agent‑only `loop.yield_turn` tool (Loop Control server).
  - Chat/inbox flows are out of scope for the initial implementation; an MCP resource mode is documented for near term.
- Container‑initiated calls MUST go through the Compositor (policy middleware enforces). A minimal async signaling layer is introduced to reflect concurrent programmatic calls without changing V1 tool return shapes.

---

## Architecture At A Glance

- Agent (MiniCodex)
  - Runs a turn when invoked; does not idle/sleep internally
  - Supports pre‑sample injection and before‑tool‑call gating by handlers
- Compositor policy middleware (in‑proc V1)
  - Enforces approvals globally (model calls + container calls) as a pre‑dispatch filter on `tools/call`
  - Does not own chat/inbox; approvals never act as wake triggers
- Compositor (FastMCP)
  - Proxy‑mounts in‑proc and remote servers under prefixes like `mcp__git_*`
  - Reuses upstream sessions; relays resources and notifications
  - Standard MCP surface: `tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources.subscribe/unsubscribe`, `prompts/list`, `prompts/get`
- Resources server (dedicated) — see `docs/mcp-runtime/resources.md`
  - Centralizes `resources/*` operations via the Compositor
  - Persists subscriptions and forwards raw notifications
  - No watermarks/HWMs; no coalescing
- UI Chat
  - Initial V1: out of scope
  - Near‑term: resource `ui://chat/inbox`; orchestrator tracks last delivered id; dual subscriptions (orchestrator + Human UI)
- Loop Control server (agent‑only)
  - `loop.yield_turn` (neutral yield tool), mounted under `mcp__loop__*`

---

## Modes & Phasing

1) V1 Sync (baseline)
   - In‑proc Compositor with policy middleware (no HTTP required)
   - Proxy‑mounted Loop Control server (agent‑only)
   - Approvals enforced by policy middleware; no separate approvals handler
   - Wake triggers: finished tool executions only (chat/inbox added later)

2) Near‑term (optional)
   - UI chat MCP resource + notifications; session‑derived HWM tools
   - Handler‑injected chat reads; optional synthetic `loop.yield_turn`

3) Async (future)
   - Tool‑state resources (`fd://tool/<id>/state`)
   - Unified async inbox with `{request_id, state}` returns and a scheduler (DNF dependencies; see “State Machine & Exactly‑Once” below)

---

## Naming & Routing

- Namespacing: `mcp__{server}__{tool}` is the canonical function name surfaced to the model.
- Compositor: use FastMCP proxy mounting for in‑proc servers and typed transports for remote.
- Routing:
  - In‑proc agent calls → Compositor (policy middleware enforces) → mounted servers
  - Container calls → Compositor over loopback (host.docker.internal); same enforcement applies
  - Resource operations → dedicated `resources` server mount
  - Do not expose upstream servers directly.

Compositor management (tools)
- Expose an admin server `compositor_admin` with safe, explicit tools for mount lifecycle. Calls route through the Compositor and are policy‑gated.
  - `attach_server({name, spec}) -> {ok}` — attach or update a server by spec (typed JSON); secrets can be masked in UI.
  - `detach_server({name}) -> {ok}` — detach a server by name; idempotent.
  - State listing: use the `compositor_meta` per‑server state resources (no `list_mounts` tool). See resources.md for details.
- Access:
  - Agent and Human may call these tools subject to policy (policy middleware enforces at tools/call time).
  - Container reconfigure also calls these tools (no direct Python path), centralizing enforcement and logging.
  - Detach/attach operations across different servers may be performed in parallel; the container batches calls concurrently and then publishes a snapshot/broadcast.

---

## Approvals (Authoritative in Compositor)

- Decisions: allow, deny_continue, deny_abort, ask (block sync; defer async)
- Mapping (sync):
  - allow → execute upstream; return result
  - ask → block until human resolves; on approve execute + return; on reject return denial
  - deny_continue → return JSON‑RPC error `policy_denied_continue` (-32951); do not execute
  - deny_abort → return JSON‑RPC error `policy_denied` (-32950); agent should abort the turn
- Source of truth: the policy middleware in the Compositor enforces approvals for all callers (agent and container). In sync mode, handlers are not involved in approvals (no pending approvals in prompt).
- Policy evaluator: a private MCP server; it may evaluate via an internal container backend. Timeouts → deny_continue with rationale recorded.

Compositor with policy middleware (V1)
- Gate `tools/call` against policy and dispatch to the appropriate mount or return a JSON‑RPC error
- Normal Compositor behavior for `resources/*` and `prompts/*` (resources are centralized by the dedicated resources server)
- Provide agent‑only Loop Control tools via a `loop` mount
Notes
- Chat notifications, resource subscriptions, and rendering are handled by the UI Chat/Resources servers and the in‑proc server/handlers — not by the policy middleware. In the initial V1, chat/inbox is out of scope.

- Server instructions & capabilities (resources)
- Expose per‑server instructions/capabilities via a dedicated `compositor_meta` server mounted under the Compositor. See docs/mcp-runtime/resources.md for the canonical resource URIs and shapes.
- Bootstrap: on attach/agent init, perform a one‑time read of these resources and inject concise summaries to the model so it understands available servers and their contracts.
- Status: Implemented; these resources are listed/readable through the front‑door Compositor endpoint.

Policy servers (split: reader, approver, proposer) & UI integration
- Split responsibilities across three MCP servers to enforce least privilege:
  - policy_reader (resources + eval tool)
    - Resources:
      - Policy text: `resource://approval-policy/policy.py` (active policy text)
      - Approvals queue: `approvals://pending/<id>` — JSON `{id, ts, kind: "tool_call"|"policy_proposal", server?, tool?, args?, proposal_id?, status: "pending"|"resolved", rationale?}`
    - Notifications: standard `notifications/resources/updated` on new/changed requests
    - Eval tool: `decide({name, arguments}) -> {decision, rationale}`
      - Default: hidden and used only by the policy middleware
      - Optional: may be exposed to agent/human tokens for testing/advisory checks; enforcement still happens only via the middleware gating real calls
  - policy_approver (human‑only tools)
    - Tools: `approve({id}) -> {ok}`, `deny({id}) -> {ok}`
    - Optional: `set_policy_text({source}) -> {ok}` or `set_policy({proposal_id}) -> {ok}` (direct edit)
  - policy_proposer (agent/model tools)
    - Tools: `propose_policy({source}) -> {id}`
- Principals
  - Agent: may call policy_proposer and policy_reader; cannot call policy_approver.
  - Human: may call policy_approver and policy_reader; does not use policy_proposer.
- Flow
  - Ask (tool‑call): policy middleware creates `approvals://pending/<id>` and blocks. Human UI (reader+approver) resolves via `approve/deny`. Middleware then executes or returns denial.
  - Proposals (policy): agent calls `policy_proposer.propose_policy` → creates `approvals://pending/<id>` (kind=`policy_proposal`). Human approves via `policy_approver.set_policy({proposal_id})` (or denies). Reader emits updates.
- Sync contract: the model does not see pending approvals; only final outcomes reach the MCP call.

Testing policy decisions (advisory)
- Optional: expose `mcp__policy_reader__decide` to agent/human tokens for testing and planning.
  - Call shape: `decide({name, arguments}) -> {decision, rationale}` where `name` is a namespaced tool (e.g., `mcp__runtime__exec`).
  - Advisory only: does not create approval items or execute anything; real enforcement happens in the policy middleware at tools/call time.
  - UI affordance: a “Test decision” control can call `policy_reader.decide(...)` on the current tool payload and show the result inline with a warning that enforcement occurs at execution time.

Container info (runtime)
- Resource: `runtime://container.info` — structured JSON describing the runtime environment (align fields closely with Docker API for familiarity), e.g. `{id, image, platform, os, arch, adgn_version, python_paths, tools:{rg:true}}`.
- Use case: let the agent adapt reads/commands to the container’s reality without trying to infer via shell.

---

## Turn Orchestration (Sync)

- Who starts turns: the in‑proc server/handlers. The agent runs one turn per invocation and does not self‑wake.
- Wake triggers (initial V1):
  - Tool results (if not in sleep_until_user)
  - Optional: admin/operator resume
  - Chat/inbox: out of scope for initial V1 (when added, chat wakes; approvals do not wake)
- Yield semantics (`loop.yield_turn`):
  - Sets an end‑turn latch consumed at the start of the next phase; the current turn ends immediately.
  - Puts the orchestrator into sleep_until_user: internal completions no longer wake new turns; results are buffered until human chat (or explicit resume).
  - Control server is agent‑only; do not expose on human connections.

Day In The Life (V1 Sync)
1) Startup: build Compositor, mount servers; attach in‑proc UI; proxy‑mount Control; load/persisted subscriptions.
2) Wake: server/handlers detect triggers (tool results; chat added later when enabled).
3) Turn start: inject pending notifications (and optional chat reads) as inputs.
4) Sample: agent produces tool calls or text; the policy middleware enforces approvals for each call and executes tools synchronously.
5) Finish: when no pending tool calls remain, end turn. If `yield_turn` was called, enter sleep_until_user.
6) Reconnects: on reconnect, re‑subscribe; optionally emit a server_restarted delta.

---

## UI Chat (Summary)

- Initial V1: out of scope
- Recommended near‑term (MCP‑native):
  - Resource: `ui://chat/inbox` (append‑only; messages + `last_id`)
  - Notifications: `notifications/resources/updated` uri=ui://chat/inbox
  - Tools (on server `ui`): `chat_read_since({after_id, limit?})` (aggregator exposes as `mcp__ui__chat_read_since`)
  - Dual subscriptions: orchestrator (pinned) and Human UI (optional/preferred)
  - Handler‑injection: on notify, inject results of `chat_read_since` (and optionally a synthetic `mcp__loop__yield_turn`) so the model sees messages as a normal tool result without an extra round
- See: `ui-chat.md` for schemas, sequences, and examples.

Resource‑specific rendering policy (summary)
- Chat (no skipping): render every message since watermark; subscribe is pinned; self‑authored events do not notify.
- Server/mount events: latest only per mount (e.g., `server_restarted`).
- Generic resources: latest‑only; Human UI can read for full fidelity when needed.

---

## Minimal Async for Container‑Initiated MCP Calls

- Rationale: programmatic MCP calls inside the container can overlap with model‑initiated calls.
- Concurrency model:
  - V1 model tool calls remain synchronous.
  - Programmatic calls reach the Compositor and may execute concurrently (optional bounded pool); the policy middleware enforces approvals.
- Tool execution states (signaling only in V1): `queued → executing → completed|error|denied|aborted`.
  - Synthetic resources: `fd://tool/<request_id>/state` with fields `{server, tool, state, ts, summary}`.
  - Use notifications to inform the agent on the next turn; returns remain synchronous for the direct caller.
- Wakes:
  - Not in sleep_until_user: tool results may wake a turn.
  - In sleep_until_user: ignore internal completions; buffer results until human chat (or resume).

---

## Transports & Security

- In‑proc baseline (V1): no HTTP/auth between agent and Compositor; use FastMCP clients/proxies in process. Approvals run as middleware inside the Compositor.
- HTTP only when crossing processes:
  - Container must connect to the Compositor with policy middleware (loopback via host.docker.internal).
  - Do not expose upstream servers directly.
  - Human UI (if remote) over UDS/loopback + JWT.
  - Policy/Approvals MCP server for Human UI:
    - In‑proc recommended when UI backend shares process (no auth required).
    - If exposed over HTTP, require human‑only auth (JWT/bearer) and do not expose to the container.

Runtime container interaction
- Container connects to the Compositor over loopback (`host.docker.internal`).
- The agent interacts with the container using a Docker exec MCP server (server `runtime`, tool `exec`), e.g., running `rg`, `cat`, etc. Approvals for these calls are enforced by the policy middleware.

Images (shared Dockerfile)
- Base Dockerfile: `docker/runtime/Dockerfile` builds a minimal image with the `adgn` package installed (includes `rg`).
- Runtime exec container: build/tag (e.g., `adgn-runtime:latest`) from the same Dockerfile; typically long‑lived per agent/session.
- Policy evaluation container: same image and runtime flags as the runtime exec container. You may still choose to launch per‑call.

Compositor HTTP access (container → host)
- Host mounts the Compositor in‑proc and also exposes a Streamable HTTP endpoint with bearer auth.
  - Bind: 0.0.0.0 on a free port (macOS/Windows: container reaches via `host.docker.internal:<port>`).
  - Linux: use `--add-host host.docker.internal:host-gateway` (Docker 20.10+) or host networking, or bind 0.0.0.0.
- Token: start with a constant bearer token; rotate to per‑session tokens later.
- Inject into runtime/exec env for in‑container clients:
  - `ADGN_COMPOSITOR_ORIGIN` (e.g., `http://host.docker.internal:8765`)
  - `ADGN_AGENT_TOKEN` (Bearer token for agent principal)
- Principal separation: do not place any human token inside the container. Human‑only tools (e.g., policy approvals) are forbidden for the agent principal.

Minimal example (in‑container Python via `mcp__runtime__exec`)
```python
import os, asyncio
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main():
    origin = os.environ["ADGN_COMPOSITOR_ORIGIN"]
    token = os.environ["ADGN_AGENT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    transport = StreamableHttpTransport(origin, headers=headers)
    async with Client(transport) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        print(names)

asyncio.run(main())
```

Container layout & mounts (for code visibility)
- Install the `adgn` package in the agent container image so code is discoverable via `importlib.resources`.
- For now, do not use a `/trusted` volume; code is read from the installed package inside the container.

OpenAI SDK Adapter (V1/Stage 2 surface)
- Function catalog: enumerate `tools/list` from the Compositor and expose tool names unchanged (e.g., `mcp__git__clone`).
- Per‑turn listing: the agent builds the tool catalog fresh each turn from the Compositor; no explicit refresh handling is required for correctness.
- Optional refresh: if a cached/static catalog is introduced, listen for `notifications/tools/list_changed` emitted by the Compositor and refresh on receipt and reconnect.
- Resource helpers (SDK adapter convenience; not MCP tools):
  - `resources_read({server, uri, start_offset?, max_bytes?}) -> {window, parts[], total_parts}`
  - `resources_subscribe({server, uri}) -> {ok}` or structured error if unsupported
  - `resources_unsubscribe({server, uri}) -> {ok}`; pinned subs may return `forbidden`
  - These helpers call MCP JSON‑RPC methods `resources/read`, `resources/subscribe`, `resources/unsubscribe` under the hood; they are not surfaced as MCP tool names.
- Errors: method‑not‑found from origin maps to structured “subscribe_unsupported”/“unsubscribe_unsupported”.

---

## Persistence & State

- SQLite overlay:
  - Mounts (Compositor): `mounts(name, prefix, spec_json, created_at)`
  - Subscriptions (Resources server): `subscriptions(server, uri, pinned, added_at)`
  - Watermarks (Orchestrator/handlers): `resource_watermarks(server, uri, last_id, source, updated_at)` — optional agent‑side table used to build notification messages/coalescing. The resources server does not manage HWMs.

State Machine & Exactly‑Once (Stage 3)
- Request states: `pending, approved, rejected, blocked, unsatisfiable, executing, completed, error, aborted`.
- Exactly‑once via lease/CAS:
  - `UPDATE requests SET state='executing', executing_lease=?, started_at=NOW WHERE id=? AND state='approved' AND executing_lease IS NULL`.
  - On completion, clear lease; on crash, mark `executing→aborted` at startup; never auto‑restart.
  - Deterministic DNF dependencies determine readiness (`[[A,B],[C]]`).

---

## Operational Guarantees

- Exactly‑once execution (lease/CAS); executing→aborted on crash; no auto‑restart
- Saturation: return `BUSY` (`-32005`); request not created
- Subscriptions: pinned chat and result subs never auto‑unsubscribe
- Coalescing: per‑URI per turn; async mode may use a brief coalescing delay
- Unified returns: single JSON‑RPC response; no double responses

- Migration Stages (summary)
- Stage 1 — Switch to FastMCP proxy mounts (completed): hand‑rolled in‑proc replaced with proxy mounts; approvals may be in handlers during transition.
- Stage 2 — V1 Simple, Synchronous Gate: install policy middleware in the Compositor; control yield; optional chat resource mode.
- Stage 3 — Composition + Unified Inbox (future): tool‑state resources; unified async returns; scheduler.

---

## Testing & Rollout

- V1 sync tests:
  - Approvals (allow, deny_continue, deny_abort, ask)
  - Yield (`loop.yield_turn`) ends turn immediately; no spurious wake in sleep_until_user
  - Sync tool completions do not auto‑wake when sleeping; chat wake does (when chat is enabled)
  - Notifications delivery formatting (raw lines; matrix/chat inbox as configured)
- Migration checkpoints:
  - Control server proxy‑mounted and agent‑only
  - Container path points to the Compositor with policy middleware
  - Handler injection verified (chat read + yield)

---

## Appendices

### A. Errors (JSON‑RPC)

- Deny (abort latch):
  ```json
  { "jsonrpc":"2.0", "error": {"code": -32950, "message": "policy_denied", "data": {"type":"policy_denied","decision":"deny_abort","reason":"…"}}, "id": 42 }
  ```
- Deny (continue):
  ```json
  { "jsonrpc": "2.0", "error": { "code": -32951, "message": "policy_denied_continue", "data": { "decision": "deny_continue", "server": "runtime", "tool": "exec", "reason": "…" } }, "id": 17 }
  ```
- Evaluator error (timeout/exception while deciding):
  ```json
  { "jsonrpc": "2.0", "error": { "code": -32953, "message": "policy_evaluator_error", "data": { "name": "mcp__server__tool", "reason": "TimeoutError: …" } }, "id": 17 }
  ```
- Subscribe unsupported:
  ```json
  { "jsonrpc": "2.0", "error": { "code": -32960, "message": "resources_subscribe_unsupported", "data": { "server": "chat", "uri": "chat://room/!abc/last" } }, "id": 7 }
  ```
- Unsubscribe unsupported:
  ```json
  { "jsonrpc": "2.0", "error": { "code": -32961, "message": "resources_unsubscribe_unsupported", "data": { "server": "chat", "uri": "chat://room/!abc/last" } }, "id": 8 }
  ```

### B. MCP Protocol Notes (resources only)

- Subscribe targets: resources only — `resources/subscribe`, `resources/unsubscribe`
- Notifications:
  - Resources: `notifications/resources/updated` (with `params.uri`)
  - Resource list: `notifications/resources/list_changed`
  - Tools list: `notifications/tools/list_changed`
  Extras are permitted but clients should still read for authoritative content.
- Reads: `resources/read`; protocol has no windowed reads/pagination (windowing is an app concern)
- Tools/prompts: no subscribe channel in the base protocol

---

## Open Questions & Follow‑Ups
- Chat resource rollout: choose when to switch from bus to MCP resource in production; finalize `ui://chat/inbox` JSON shape and MIME.
- Subscriber identity mapping: ensure stable identity across token rotations (UI server mapping if tokens change).
- Tools list refresh: ensure we subscribe to and handle `notifications/tools/list_changed` consistently across in‑proc and HTTP paths; refresh SDK tool list on receipt and reconnect.
- Minimal async signaling: exact coalescing policy and whether some completions should suppress wake by default.
- Error code namespace: confirm -32950/-32951/-32953 don’t collide with any existing codes used upstream.
- Loop yield edge cases: resolved — approvals/resolutions do not wake. When chat is enabled, chat and finished tool results wake; otherwise only finished tool results.
- Matrix integration: staged as a separate doc; defer until UI chat resource mode is stable.
