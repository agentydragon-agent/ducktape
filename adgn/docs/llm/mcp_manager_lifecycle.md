# MCP Manager — Lifecycle, Sampling, and Tool/Resource Exposure

Status: proposal (v1)

## Goals

- Enforce the single-task lifecycle invariant for all MCP servers and their underlying task-groups.
- Provide a coherent, versionable “sampling snapshot” (banner + tools) for the model per turn.
- Support dynamic attach/detach/restart (future), with a simple initial policy: all configured servers are desired-enabled and exposed unless they fail initialization.
- Keep API small and predictable for MiniCodex and similar agents.

## TL;DR — tight plan

- Single owner actor (one asyncio.Task) owns one AsyncExitStack and performs all opens/inits/closes.
- Control plane (serialized by actor): AttachSpec (auto‑start), DetachSpec, RestartSpec, ListSpecs, ShutdownAll.
- Data plane: EnsureOpen (idempotent), get_session, list_tools_namespaced, call_tool_namespaced, resources_*.
- Sampling: one atomic snapshot per turn (banner + namespaced tools) from Running servers only; Failed excluded.
- Namespacing is manager‑owned (internal helpers); external code uses list_tools_namespaced / call_tool_namespaced.
- Initialize once per server start; cache InitializeResult; banner built from cached instructions only (no re‑init mid‑turn).

## Invariant (must hold)

All enter/exit of MCP servers (transports, sessions, any anyio TaskGroups/cancel-scopes they create) MUST be performed by the same task/cancel-scope owner. Practically:

- Every `spec.open(stack)` and the corresponding `stack.__aexit__` are executed by one “owner task.”
- No other task calls `enter_async_context` or `__aexit__` on the shared `AsyncExitStack`.

This prevents the anyio error:

```
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

## Architecture

- Owner task (actor pattern): one `asyncio.Task` runs the lifecycle loop (we use this up‑front, not later).
- One `AsyncExitStack` owned by the actor; never touched outside the actor task.
- A command queue (`asyncio.Queue`) for lifecycle operations. `AttachSpec` automatically opens + initializes (auto‑start) in the owner; `EnsureOpen` is an idempotent accessor for callers that “just need it running.”
- On `__aenter__`, the manager starts the owner and issues `AttachSpec` for all configured specs so everything desired‑enabled comes up under the actor immediately.

### Server state (per name)

Minimal tracking (expandable later):

- `realized: ServerSlot | None`
- `init: InitializeResult | None` (cached full initialize result, including `instructions`, `serverInfo`, etc.)
- `state: Detached | Running | Failed`
- `last_error: str | None`

Simplified policy (per user request):

- All servers are “desired enabled” (we always attempt to start).
- Exposure is `true` for all successfully initialized servers; failed ones are not exposed.

## Initialization lifecycle

On `__aenter__` of `McpManager`:

1. Create and enter a single `AsyncExitStack` in this task.
2. Eagerly open all configured specs using that stack (same task) — equivalent to calling AttachSpec for each with auto-start.
3. For each realized slot, initialize the underlying session and store the full `InitializeResult` (`init`).
4. Mark server `state=Running` on success, else `state=Failed` and fill `last_error`.

On `__aexit__`:

- Exit the `AsyncExitStack` in this task. Because all enters occurred in this task, anyio teardown stays in-scope and consistent.

## Structured models (Pydantic)

Use Pydantic models for all structured returns and notifications. The manager returns these models; prompt/banner rendering is a separate concern outside the manager.

```python
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

class InitializeView(BaseModel):
    instructions: str | None = None
    serverInfo: Any | None = None

class ServerEntry(BaseModel):
    name: str
    state: Literal["running", "failed"]
    initialize: InitializeView | None = None
    error: str | None = None

class ToolDef(BaseModel):
    type: Literal["function"] = "function"
    name: str  # namespaced: mcp__server__tool (manager-owned)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

class SamplingSnapshot(BaseModel):
    servers: list[ServerEntry]
    tools: list[ToolDef]

# Notifications (polled by agent before each sampling)
class ResourceUpdateEvent(BaseModel):
    server: str
    uri: str
    version: int  # monotonically increasing counter per (server, uri); no wall-clock time exposed

class NotificationsBatch(BaseModel):
    resources_updated: list[ResourceUpdateEvent] = Field(default_factory=list)
    tools_invalidated: list[str] = Field(default_factory=list)  # server names
```

Manager APIs return these models:
- `await mcp.sampling_snapshot()` → SamplingSnapshot
- `await mcp.poll_notifications()` → NotificationsBatch (and clears the buffers in the owner actor)

## Sampling snapshot (what the model sees per turn)

Expose a single atomic snapshot for agents to use:

```python
snapshot = await mcp.sampling_snapshot()
# snapshot = {
#   "servers": [
#       {"name": "git-ro", "state": "running", "instructions": "...", "serverInfo": {...}},
#       {"name": "submit_commit_message", "state": "running", "instructions": "..."},
#       # failed servers included with state="failed" and error for observability
#   ],
#   "tools": [...],  # merged tool defs from running servers
#   "banner": "FYI: MCP servers/resources..."  # built from cached InitializeResult.instructions etc.
# }
```

Guidelines:

- Only include tools from `state==Running` servers.
- `banner` is generated once per snapshot from cached `InitializeResult` data (no re-initialize).
- The snapshot is assembled entirely within the owner task (no races).

### Tool listing (for Responses API tool wiring)

- Use existing `list_tools()` on each running session and map to OpenAI/Anthropic tool definitions:
  - `{type: "function", name: "mcp__<server>__<tool>", description, parameters}`
- The manager returns a merged list: `snapshot["tools"]`.
- Agents should pass `snapshot["tools"]` directly to `Responses.create`.

### Instructions banner (system header augmentation)

- Use cached `InitializeResult.instructions` per server to build the merged banner:
  - `FYI: MCP servers/resources:\n- server=<name>\n  resources: [first 5 URIs] (+N more; list via mcp__resources__list)\n  <name server desc>...\n  </name server desc>`
- This mirrors the existing `render_banner()` behavior but avoids re-fetching state mid-turn.

## Tools cache & change notifications

- Manager caches per-server tool lists and an aggregate list for sampling.
- Invalidation:
  - On receipt of `notifications/tools/list_changed` from a server, the owner actor invalidates that server’s tools cache and the aggregate cache.
  - Callers can also explicitly `invalidate_tools_cache([server])` (internal API) when making control-plane changes.
- Sampling behavior:
  - `sampling_snapshot()` first ensures caches are fresh (respecting invalidations), then returns the aggregate list for Running servers only.

## Resources (list/read)

- The Resources MCP helper remains a synthetic server automatically attached by the manager.
- Capability‑gated: only servers that advertised `capabilities.resources` in `initialize` are queried for resources.
- URIs are server‑scoped (not globally unique); always qualify with server name in notifications, subscriptions, and reads.
- Subscriptions:
  - Manager exposes resource subscribe/unsubscribe via the underlying session for servers that declare `capabilities.resources.subscribe`.
  - On `notifications/resources/updated` from a server, the owner actor records a queued resource-update event with `{server, uri, ts}`.
- Resource operations for agents/tests:
  - `await mcp.list_resources(only=[...])` or the typed `resources_list()` which returns `ResourcesListResponse`
  - `await mcp.read_resource(server, uri)` or the typed `resources_read()` which returns windowed `ResourcePart` slices
- Windowing API (text/base64) ensures large blobs are page‑able; agents should **not** inline large resources into prompts — prefer `resources_read()` windows when needed.

## Public API sketch (actor from the start)

```python
class McpManager:
    # Control plane (serialized by owner):
    async def attach_spec(self, name: str, spec: ServerSlotSpec, expose: bool = True) -> None: ...  # auto-start
    async def detach_spec(self, name: str) -> None: ...
    async def restart_spec(self, name: str) -> None: ...

    # Data plane:
    async def ensure_open(self, name: str) -> ServerSlot: ...  # idempotent accessor (starts if needed)
    async def get_session(self, name: str) -> ClientSession: ...

    # Introspection:
    async def list_specs(self) -> dict[str, dict]: ...
    async def sampling_snapshot(self) -> dict[str, Any]: ...  # atomic {servers, tools, banner}

    # Lifetime:
    async def __aenter__(self) -> McpManager: ...  # start owner; attach_spec all configured
    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    # Cached initialize accessor (used by banner/resource gating):
    async def get_server_initialize(self, name: str) -> InitializeResult: ...
```

_(Future: when we add dynamic attach/detach/restart, we’ll switch to a full actor with a command queue, and keep the same sampling_snapshot facade.)_

## Agent delivery semantics for resource updates

- Notifications do not initiate turns. If they arrive outside a turn, they are buffered.
- If a notification arrives during a turn, it is delivered at the next opportunity (immediately after the currently pending tool result is emitted, or just before the next sampling call), as a system message of the form:
  - `Agent FYI: Resource updated (server=<name>, uri=<uri>)`
- Delivery is idempotent per `(server, uri, generation)`; duplicates are coalesced per turn.
- A delivered FYI triggers a normal sampling step (the agent can choose how to respond—ignore, refresh, or call a tool).
- No MCP hop for polling: pre-turn delivery is done via direct Python calls from the agent/handler to the manager, not via an in-proc MCP server.
- Manager API:
  - `await mcp.subscribe_resource(server, uri)` and `await mcp.unsubscribe_resource(server, uri)` (only when capability present).
  - `mcp.poll_notifications()` → returns and clears buffered notifications (owner actor gathers; agent injects them as system messages when building input for the next sampling, into the transcript—not the instruction preface—for a consistent history).

Agent hook (pseudo-code) — legacy (now handled by NotificationsHandler; no direct polling in agent):
```python
# Before building instructions/tools and calling Responses.create
batch = mcp.poll_notifications()
for ev in batch.resources_updated:
    # Concise, machine-friendly FYI; agent refers to Notifications server instructions
    payload = {"server": ev.server, "resource": ev.uri, "version": ev.version}
    transcript.append(SystemMessage(content=json.dumps(payload)))
# tools_invalidated is handled implicitly by fresh sampling_snapshot()
```

## Opt-in NotificationsHandler usage

Notification delivery is opt-in. Callers explicitly add the handler when constructing MiniCodex:

```python
from adgn.llm.mini_codex.aggregating_handler import NotificationsHandler, AutoHandler

handlers = [
    NotificationsHandler(mcp),  # opt-in delivery of batched resource FYIs
    AutoHandler(),              # your loop controller(s)
    # ... other handlers ...
]
mini = await MiniCodex.create(
    model=model,
    mcp=mcp,
    client=client,
    handlers=handlers,
    system=system,
)
```

MiniCodex does not auto-wire handlers; this maintains the explicit handler contract.

## MiniCodex usage pattern

```python
async with McpManager(specs) as mcp:
    snapshot = await mcp.sampling_snapshot()
    resp = await client.responses.create(
        model=model,
        input=messages,
        tools=snapshot["tools"],
        instructions=base_system + "\n\n" + snapshot["banner"],
        tool_choice="auto",  # or from loop policy
        parallel_tool_calls=True,
        store=True,
    )
```

- On subsequent turns, re-fetch `sampling_snapshot()` to reflect any runtime failures/restarts and to pick up any invalidated tool caches.
- Only servers in `state==running` are exposed; failures won’t break sampling.
- Before each sampling, the agent should `await mcp.poll_notifications()` and inject any FYIs as system messages to the model input.
## Migration plan: centralize namespacing and calls

Replace scattered build/parse usage with McpManager helpers.

Scope (from code search):
- adgn/src/adgn/llm/mini_codex/agent.py (parse_mcp_function on tool calls)
- adgn/src/adgn/llm/mini_codex/event_renderer.py (parse_mcp_function)
- adgn/src/adgn/llm/mini_codex/approvals.py (build/parse)
- adgn/src/adgn/llm/git_commit_ai/minicodex_backend.py (build_mcp_function in bootstrap)
- adgn/src/adgn/llm/mcp/helpers.py (build_mcp_function)
- adgn/src/adgn/llm/properties/{lint_issue.py, grade_runner.py} (build_mcp_function)
- tests under adgn/tests/llm/** using build/parse (adjust to new helpers or keep tiny test-only util)

Steps:
1) Add to McpManager:
   - list_tools_namespaced(only=None) -> list[tool defs]
   - call_tool_namespaced(name, arguments) -> CallToolResult
   - (internal) _build_tool_name/_parse_tool_name; optionally expose stable adgn.llm.mcp.naming for tests
2) Switch MiniCodex:
   - On tool-call: use call_tool_namespaced(call.name, call.arguments)
   - For sampling: use sampling_snapshot()["tools"] (names already namespaced)
3) Switch bootstrap sites (Git RO, properties runners) to build names via manager util or namespaced constant if needed
4) Tests:
   - Prefer namespaced helpers from McpManager or adgn.llm.mcp.naming; avoid direct f-strings

Behavioral guardrails:
- Names passed to OpenAI must be of the form mcp__server__tool (manager-owned)
- Arguments accepted as dict or JSON string; call_tool_namespaced validates/normalizes
- Sampling excludes Failed servers (tools/banner)

## Error handling and failed state

- If a server fails initialization, we record `state=Failed`, set `last_error`, and exclude it from sampling (tools/banner). `list_specs()` surfaces the failure for diagnostics.
- `restart_spec(name)` transitions Failed/Running/Detached → Starting → Running (or back to Failed), rewriting `init`/`last_error` appropriately.
- Teardown exceptions are surfaced; with the invariant, anyio shutdown runs in the owner task and should not raise the cancel‑scope mismatch.

## Owner actor (implemented)

We use a serialized lifecycle loop (single owner task) from the start:

- Commands:
  - `AttachSpec(name, spec, expose=True)`: add/replace spec and auto-start (open + initialize immediately in the owner task). On success: `state=Running`, cache `InitializeResult` and mark exposed.
  - `EnsureOpen(name)`: idempotent; returns realized slot, starting if not already running.
  - `DetachSpec(name)`: gracefully stop and remove from registry; `state=Detached`.
  - `RestartSpec(name)`: detach then attach (auto-start) in-order.
  - `ListSpecs()`: returns a snapshot of server states (`running/failed/detached`), last_error (if any), and whether `init` is cached.
  - `ShutdownAll()`: orderly shutdown in the owner task.
- Owner loop: processes commands, performs `spec.open(stack)` and initialization (AttachSpec/EnsureOpen) and `stack.__aexit__` (Detach/Shutdown) in-order, in the same task to satisfy anyio’s cancel-scope invariant.
- `sampling_snapshot()` stays the facade; implementation gathers from the actor-owned registry and includes only servers with `state==Running` (failed are excluded from tools/banner).

### Concurrency and error propagation

- Multiple concurrent `EnsureOpen(name)` calls deduplicate to one attach/open; callers await the same result.
- If open/init fails, the exception is returned to the caller and the server is recorded as `state=Failed` with `last_error`.
- Runtime calls (`list_tools`, `call_tool`, `resources_read`) do not manipulate cancel scopes and can be called from any task once the server is Running.

### Sampling integration

- The owner constructs `sampling_snapshot()` atomically: tools from Running servers only, and a merged banner from cached `InitializeResult.instructions`.
- On each turn, agents fetch a fresh snapshot to reflect any hot restarts/failures without risking partial views.

## Open TODO: composability of pre‑sample inserts vs synthetic actions

Current model (handlers return Continue with inserts, or SyntheticAction to skip sampling) is not fully composable:
- Some hooks (e.g., git‑ro bootstrap) implicitly assume they run last before sampling; other hooks that also inject system messages can reorder/clobber expectations.
- Synthetic actions that need to “do work now” and then contribute messages risk interfering with other hooks’ inserts if everything shares one pre‑sample boundary.

Direction:
- For hooks that need immediate execution and a well‑defined local trace, run an internal sub‑agent loop inside the handler and return only its message trace (to be appended) instead of relying on global pre‑sample ordering.
- Keep simple “reminder” hooks as pure inserts (system FYIs) and make aggregation strictly additive; no overwrites.
- Consider explicit handler priorities or a two‑phase pipeline (execute → insert) to avoid ordering hazards.

This keeps “do work now” isolated, and makes pre‑sample inserts predictable.

## Diagnostics (planned additions)

We will add light-weight diagnostics routed through the owner (no external enter/exit):

- Per-server ring buffers:
  - `events`: bounded deque capturing lifecycle events (started, initialized, failed, restarted, stopped), with timestamps.
  - `logs`: a small text ring buffer writable by the owner on notable transitions and error traces.
- Commands:
  - `GetEvents(name, limit=50)` → list of `{ts, level, event, detail}`.
  - `GetLogs(name, limit_bytes=4096)` → tail text from the log buffer.
- None of these commands perform enter/exit; they only read actor-owned state, preserving the invariant.

## Implementation status (as of now)

- [x] Structured models (Pydantic): InitializeView, ServerEntry, ToolDef, SamplingSnapshot, ResourceUpdateEvent, NotificationsBatch
- [x] McpManager.sampling_snapshot() returning typed SamplingSnapshot (Running-only tools)
- [x] McpManager tool namespacing facade: list_tools_namespaced(), call_tool_namespaced()
- [x] Per-server tool cache + explicit invalidation API (invalidate_tools_cache_for)
- [x] Notification buffering + per-(server, uri) version counters; poll_notifications() returns typed batch
- [x] MiniCodex: uses sampling_snapshot() for tools; banner derived from structured snapshot (no getattr)
- [x] MiniCodex: handler-based pre-turn notification delivery → JSON FYIs appended to transcript (system messages)
- [ ] Owner actor (single task) managing all open/init/close; command queue with Attach/Detach/Restart/EnsureOpen/ListSpecs/ShutdownAll
- [ ] Wire MCP server notifications → manager.notify_tools_list_changed/notify_resource_updated in the owner actor
- [ ] Tools cache invalidation on notifications (currently API exists; auto-wiring pending)
- [ ] Resource subscription exposure (subscribe_resource/unsubscribe_resource) with capability gating and error messages
- [ ] Centralize namespacing usages (agent/event_renderer/approvals/helpers) to manager facade (migration plan section)
- [x] Reducer support for Continue.inserts (typed OpenAI SDK message objects) and well-defined composition/ordering
- [x] Optional handler-based notifications delivery (replace agent pre-turn poll with a handler that returns inserts)
- [ ] Composability improvement (see Open TODO): sub-agent loop for “do work now” hooks; two-phase execute→insert pipeline/priorities
- [ ] Tests: unit (manager caches/notifications), integration (in-proc servers, list_changed/updated), concurrency (ensure_open dedupe)
- [ ] Decide on _build_effective_instructions banner: keep minimal banner behind a flag (include_mcp_banner) or remove; ensure no duplication with transcript FYIs and tool exposure

## Notifications MCP server — instructions and JSON FYIs

We provide a tiny in‑proc MCP server `notifications` with rich instructions, so the agent understands the contract. The server exists primarily to document the protocol to the model; polling still occurs via direct Python calls (no MCP hop) as described above.

- Server name: `notifications`
- initialize.instructions (human‑/model‑readable):
  - Explains that the agent will receive concise system FYIs in the transcript of the shape:
    - `{ "server": "<name>", "resource": "<uri>", "version": <int> }`
  - `version` is a monotonically increasing counter per `(server, uri)` maintained by the manager; no wall‑clock timestamps are exposed.
  - Advises the agent how to react (e.g., optionally call `mcp__resources__read` with windowing if it needs the latest content).
- Tools:
  - Optionally mirror manager functions (e.g., `subscribe_resource`, `unsubscribe_resource`) for symmetry, but the pre‑turn polling remains a direct Python call.

This keeps FYIs terse while giving the agent a stable, documented schema to rely on.

- [ ] TODO: Verify Responses API accepts injected transcript FYIs with role="system" alongside normal user/assistant/function_call items; adjust to a safe role if required by API (e.g., assistant with a prefix).
## MCP Python ecosystem: notifications and feature coverage

Summary:
- Both the official modelcontextprotocol/python-sdk and fastmcp support server→client change notifications (tools/resources/prompts list_changed and resources updated). Servers can emit them; clients receive them via a message/notification handler. The python-sdk also exposes dedicated helpers for logging and progress notifications; fastmcp wraps the same client and queues notifications on the server side.

Notifications (server → client):
- `notifications/tools/list_changed`
- `notifications/resources/list_changed`
- `notifications/resources/updated`
- `notifications/prompts/list_changed`
- `notifications/message` (logging)
- `notifications/progress`

Client → server:
- `notifications/initialized`
- `notifications/roots/list_changed`

Feature comparison (Python frameworks):

| MCP Feature (2025‑06‑18) | modelcontextprotocol/python-sdk | fastmcp |
| --- | --- | --- |
| Protocol negotiation (protocolVersion) | Yes | Yes (via python-sdk types) |
| Initialize handshake (InitializeRequest/Result) | Yes | Yes (client built on python-sdk) |
| Client Initialized notification (notifications/initialized) | Yes (client sends) | Yes (via python-sdk client) |
| ServerInfo/instructions in initialize | Yes | Yes |
| Server capability gating (tools/prompts/resources) | Yes | Yes |
| Tools: list (schema, parameters) | Yes | Yes |
| Tools: call_tool | Yes | Yes |
| Tools: outputSchema on tools | Yes | Yes |
| Tools: structuredContent validation (client) | Yes (validates) | Yes (and typed parsing to Python types) |
| Tools: list_changed notification | Yes (send_tool_list_changed; client receives) | Yes (server queues/flushes; client receives) |
| Prompts: list/get | Yes | Yes |
| Prompts: list_changed notification | Yes (send_prompt_list_changed; client receives) | Yes (server queues/flushes; client receives) |
| Resources: list (with pagination/cursor) | Yes | Yes |
| Resources: read (windowed parts) | Yes | Yes |
| Resources: subscribe/unsubscribe | Yes (client session) | Underlying session yes; wrapper partial |
| Resources: list_changed notification | Yes (send_resource_list_changed) | Yes (queues/flushes) |
| Resources: updated notification | Yes (send_resource_updated) | Yes (queues/flushes) |
| Logging message notification (notifications/message) | Yes (send_log_message; client logging callback) | Yes (uses same) |
| Progress notification (notifications/progress) | Yes (per-request progress callbacks) | Yes (uses same) |
| Roots/list_changed (client capability) | Yes (client declares roots; TODO in code comment on semantics) | Yes (via python-sdk types) |
| Transports: stdio | Yes | Yes |
| Transports: SSE | Yes | Yes |
| Transports: Streamable HTTP | Yes | Yes |
| Streaming/partial results pattern | Progress + streaming transports | Same |
| Reconnection/retry behavior | Manual; no built-in auto-reconnect | Manual; reentrant client; no built-in auto-reconnect |
| Lifespan/lifecycle hooks (server) | Yes (lifespan context) | Yes (Context helpers) |
| Pagination/windowing helpers | Yes | Yes |
| Typed structured-output parsing convenience | Basic validation | Enhanced (json_schema_to_type) |

Sources:
- Spec: https://modelcontextprotocol.io/specification/2025-06-18
- python-sdk server notifications: https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/session.py
- python-sdk client notifications: https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/session.py
- Resources subscribe/unsubscribe (python-sdk): https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/session.py
- Structured outputs (python-sdk README): https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
- Protocol types (LATEST_PROTOCOL_VERSION): https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/types.py
- fastmcp server notification queueing: https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/server/context.py
- fastmcp client wrapper (typed parsing + transports): https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/client/client.py

Notes:
- Neither library auto-refreshes local tool/resource lists on receipt of list_changed; consumers should refresh explicitly upon notification.
- Resource subscription is supported in python-sdk’s client; fastmcp’s wrapper can use session.subscribe_resource/unsubscribe_resource even if convenience methods are not exported.

## Acceptance criteria

- Clean shutdown: no anyio cancel-scope mismatch on `__aexit__`.
- Coherent snapshots: tools + banner reflect the same instantaneous state.
- Large outputs are bounded: resource/window APIs and (for git) diff/list pagination ensure snapshots fit model context.
- Easy adoption: MiniCodex and other agents swap separate `render_banner()`/`list_tools()` calls for one `sampling_snapshot()`.

## Namespacing ownership & visibility

- Ownership: McpManager is the sole owner of namespacing.
- Internal helpers (non‑public): `_build_tool_name(server, tool)` and `_parse_tool_name(name)` live inside McpManager (or a nested helper class) and are used by manager APIs.
- Public surface (preferred):
  - `list_tools_namespaced()` — returns OpenAI/Anthropic‑ready tool defs with names like `mcp__server__tool`.
  - `call_tool_namespaced(name, arguments)` — takes the namespaced string and routes to the right server/tool with argument parsing and result serialization.
  - `sampling_snapshot()` — tools already namespaced; callers don’t build/parse names themselves.
- Rare external use (tests/prompt building): if needed, provide a very small, stable utility under `adgn.llm.mcp.naming` (opt‑in) with `build_tool_name` and `parse_tool_name`. This avoids reaching into manager internals while keeping the main namespacing logic centralized. If not needed, keep helpers internal only.

## Handling OpenAI namespaced tool calls

OpenAI Responses will return function calls with a namespaced tool name and arguments. In this design we handle them by:
- Parsing the canonical name `mcp__<server>__<tool>`
- Ensuring the server session is open (already true under eager-open; still idempotent)
- Parsing arguments (dict or JSON string)
- Calling the MCP tool via the manager and serializing the result for Responses replay

Example (raw call + raw serialization):

```python
from adgn.llm.mini_codex.mcp_manager import parse_mcp_function
from adgn.llm.mini_codex.agent import _responses_output_from_calltool  # reuse exact serializer

async def handle_responses_tool_call(mcp: McpManager, name: str, arguments: dict | str | None) -> str:
    """Return the output string to emit as function_call_output for Responses replay."""
    server, tool = parse_mcp_function(name)  # e.g., "mcp__git-ro__git_diff" -> ("git-ro", "git_diff")
    # Note: call_tool accepts either a dict or JSON string and validates object shape
    call_result = await mcp.call_tool(server, tool, arguments)
    # Convert MCP CallToolResult to the output string that Responses expects
    return _responses_output_from_calltool(call_result)
```

Typed variant (servers that return `structuredContent['result']`):

```python
from pydantic import BaseModel

class DiffStatPage(BaseModel):
    items: list[dict]
    truncated: bool
    next_offset: int | None = None
    total_count: int

async def get_stat_typed(mcp: McpManager, name: str, args: dict | str | None) -> DiffStatPage:
    server, tool = parse_mcp_function(name)
    # Enforce the contract: server must return structuredContent with a top-level 'result'
    page = await mcp.call_tool_typed(server, tool, args, result_model=DiffStatPage)
    return page
```

Notes:
- Only servers in state==Running are exposed in `sampling_snapshot()`; failed servers are excluded, so tools passed to the model are always callable.
- Arguments may be None, a dict, or a JSON string. `call_tool` validates and converts strings to dicts, returning an MCP error object (serialized to `{ok: false, error: ...}`) instead of raising on JSON shape errors.
- For large outputs (patches/resources), callers should pass slice/list pagination in arguments and make follow-up calls using `next_offset` values returned by servers.
