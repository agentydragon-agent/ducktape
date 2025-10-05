# MiniCodex Interactive UI — Summary

This document summarizes the interactive UI and approvals integration for MiniCodex.

Implemented

- Approvals at the agent boundary
  - ApprovalPolicyHandler + ApprovalPolicyEngine + ApprovalHub gate MCP tool calls (ask/allow/deny).
  - MiniCodex.create can inject the handler when given `approval_engine` and `approval_hub`.
  - NotificationsHandler inserts compact system messages when approval_policy resources change.

- HTTP UI (FastAPI + WebSocket)
  - src/adgn/agent/server/app.py serves the UI and wires the WS endpoint.
  - UI renders UiState (messages + tool groups) and pending approvals; supports send/abort.
  - State arrives via `ui_state_snapshot` + `ui_state_updated` WS messages only (REST removed).
  - UI resolves approvals by signaling ApprovalHub (Allow/Deny) per pending call.
  - Frontend: src/adgn/agent/web (built to src/adgn/agent/server/static/web).

- MCP server: approval_policy (optional)
  - adgn/mcp/approval_policy/server.py exposes:
    - Resources: `approval-policy://policy.py`, `approval-policy://proposals/{id}.json`.
    - Tools: `propose`, `withdraw`, `get_status` (apply is UI-only via engine).

Usage (high level)

- Enable approvals and UI:
  - Create engine + hub, inject into agent:
    - `engine = ApprovalPolicyEngine(); hub = ApprovalHub()`
    - `agent = await MiniCodex.create(..., approval_engine=engine, approval_hub=hub)`
  - Optionally expose `approval_policy` MCP: `ApprovalPolicyServer(engine)` via in-proc spec.
  - Start the UI server (src/adgn/agent/server/app.py) and connect the browser client.

- Headless mode:
  - Omit approvals or auto-resolve via a small driver that resolves ApprovalHub with Continue.

Remaining / Follow‑ups

- UI/UX
  - Nicer rendering (tool-specific views, better logs), multi-session management, auth.
  - Streaming tokens view; richer keyboard shortcuts.

- Approvals
  - Optional resource read gating; persistence/versioning for policies; sandboxed policy execution.

References

- Agent: `adgn/agent/agent.py`
- Approvals: `adgn/agent/approvals.py`
- UI server: `src/adgn/agent/server/app.py`
- MCP approval policy server: `adgn/mcp/approval_policy/server.py`

Component details
1) Approval policy handler (modular, not tightly coupled)
- Module: src/adgn/agent/approvals.py
- Models
  - Modes: allow | deny_continue | deny_abort | ask (policy decides)
  - ApprovalContext passed to policy with attributes: server, tool, arguments
  - ApprovalHub: rendezvous for pending tool approvals (UI resolves decisions)
- Handler class
  - ApprovalPolicyHandler(engine, hub): injected as the first handler; gates tool calls before MCP execution and coordinates ask/deny paths.
- Resources and approvals (note for MVP/follow‑up)
  - The agent uses both tools and resources (mcp__resources__list/read and manager.read_resource()). The same policy engine may be extended to gate resource reads if desired.
  - Minimal approach: treat resource read as a virtual key like "resource_read::{server}" (include {uri} in the pending event payload for context). Policy can say ask/allow at server granularity; UI shows the exact URI before approving.
  - list_resources() stays allow; read_resource(server, uri) consults policy and, if "ask", emits approval_pending {kind:"approval_pending", call_id, type:"resource_read", server, uri} and awaits a decision.
- Agent integration
  - No changes to the MCP manager. Pass approval_engine + approval_hub to MiniCodex.create so it prepends ApprovalPolicyHandler to the handler stack.
- Minimal UX: When a tool call is "ask", the UI shows Pending Approvals from ApprovalHub with Allow/Deny controls. Deny resolves the hub with an Abort or an Injected structured error (policy-defined); Allow resolves with Continue.

2) HTTP UI server
- New modules: src/adgn/agent/server/
  - app.py: FastAPI app; registers routes and WS
  - ws.py: WebSocket handlers
  - runtime.py: AgentSession and connection manager
  - static/web/index.html: Built UI assets (output of Vite build)
  - Simple page includes:
    - Chat pane (UiState items),
    - Tool approvals list (checkbox per tool; sections per MCP server),
    - Textarea input and Send button,
    - Abort button.
- Backend responsibilities
  - Start/own an AgentSession that wraps MiniCodex (one at a time initially):
    - Holds approvals manager and exposes set_preapproved(tool_key: str, allowed: bool).
    - run(prompt): create asyncio.Task to call agent.run(user_text=prompt), forward agent events to connected WebSocket clients.
    - abort(): cancel the task; catch asyncio.CancelledError and emit {kind: "aborted"} to UI.
  - Event bridge: register a handler to forward dict events from _emit_event to WebSocket as JSON lines, and append them to an in-memory transcript served by /transcript. Also forward approval lifecycle events: approval_pending {call_id, kind:"tool"|"resource_read", tool|{server,uri}, args?}, approval_decision {call_id, allowed}.
  - Endpoints
    - GET / -> serves static index.html
    - GET /transcript -> returns JSON list of event records from the in-memory transcript (for F5 reload/rollout history)
    - WebSocket /ws: duplex channel:
      - Outbound: emit events (user_text, assistant_text, tool_call, function_call_output, tool_error), approval_pending, approval_decision, and synthetic notifications (aborted, status).
      - Inbound messages:
        - {type: "send", text: "..."} -> appends a user message and triggers agent.run(text)
        - {type: "approve", call_id: string} / {type: "deny", call_id: string} -> resolve ApprovalHub for that call_id with Continue or Abort/BypassToolInjectOutput
        - {type: "abort"} -> orchestrator cancels the outer task running agent.run()
  - Keyboard shortcuts: In index.html, attach keydown listener for Cmd/Ctrl+Enter to send; Shift+Enter inserts newline (browser default).
- Launch entrypoint (optional now): small CLI to run the server, eg: adgn-mini-codex-ui --port 8765

3) Abort model rollout and abort-turn semantics

Responses API invariant (must-answer-all tool calls)
- For every ResponseFunctionToolCall the model emits in a response, we must emit exactly one function_call_output back before attempting another sampling call.
- On approval denial within a batch of tool calls:
  - The agent catches TurnAbortRequested for the denied call and emits a synthetic function_call_output (structured error) for that specific call.
  - For any remaining tool calls in the same batch that were not executed yet, the agent emits synthetic function_call_output records with a minimal error payload (e.g., {ok:false, error:"turn aborted"}). If some calls were already in-flight, await their completion or replace with the synthetic error output, but ensure every call_id gets exactly one output.
  - After all function_call_output messages for that batch are emitted, the agent ends the turn (does not sample again).
- Session.run() may be wrapped in a task by the orchestrator (UI/CLI) for user-initiated Abort.
- Abort-TURN on approval denial:
  - The handler returns Abort or BypassToolInjectOutput; the agent emits a structured function_call_output for each pending call_id (the denied one and any remaining in the batch as minimal aborted errors) and ends the turn immediately. No task cancellation needed; API is UI-agnostic.
- Abort-BUTTON (user-triggered stop): orchestrator cancels the outer task running agent.run(); server emits {kind:"aborted"}. Phase 2 can track per-tool tasks to cancel mid-batch if desired.

Wire-up and minimal code edits

Agent-awareness (handler injection)
- MiniCodex accepts an approvals engine and hub; when provided, it prepends ApprovalPolicyHandler to the handler chain. If you omit them, behavior is unchanged and the agent runs without approvals.
- The MCP manager surface remains unchanged (list_tools, list_resources, read_resource, call_tool).
- Example wiring:
  - base = McpManager(slots)
  - engine = ApprovalPolicyEngine(); hub = ApprovalHub()
  - await MiniCodex.create(..., mcp=base, approval_engine=engine, approval_hub=hub, ...)

API stubs (for clarity; implementation follows these shapes)
```python
from typing import Protocol, Any

class McpManagerProtocol(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...
    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> Any: ...

class ApprovalHub:
    async def await_decision(self, call_id: str, request: dict[str, Any]) -> Any: ...
    def resolve(self, call_id: str, decision: BeforeToolCallDecision) -> None: ...

class ApprovalPolicyHandler:
    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision: ...
```

- Agent uses manager-level call_tool/read_resource; approvals logic is isolated in ApprovalPolicyHandler and ApprovalHub.
- New modules
  - src/adgn/agent/approvals.py (policy/state/manager)
  - src/adgn/agent/server/app.py (FastAPI app)
  - src/adgn/agent/server/static/web/index.html (built UI)
- No changes to Reducer/handlers in Phase 1.

Data and event contracts
- Reuse existing dict events emitted by agent._emit_event():
  - user_text, assistant_text, tool_call {name,args,call_id}, function_call_output {call_id, output, name}, tool_error {name, call_id, error}
- UI websocket message shapes
  - From server -> client: pass-through event objects + {kind:"aborted"}
  - From client -> server:
    - {type:"send", text:string}
    - {type:"setApproval", tool:string, allowed:boolean}
    - {type:"abort"}

Security and ops
- Bind HTTP server to 127.0.0.1 by default; no auth for local dev.
- CORS disabled (same-origin only) in minimal version.
- No file writes; all state lives in-process (transcript/approvals in memory) for MVP.
- No explicit backpressure handling in MVP; UI may drop/clip client-side only for rendering.
- Large outputs: append to transcript; cap in UI display with expandable blocks.

Phased plan
- Phase 1 (MVP)
  - ApprovalPolicyHandler + ApprovalHub + minimal UI glue
  - HTTP UI with transcript, pending approvals (Allow/Deny), compose box, abort button
  - Single session, single agent at a time; manual run start via UI
- Phase 2
  - Policy persistence and patterns (optional): move hardcoded policy into a small module or JSON; add wildcard support later
- Pretty rendering for certain tools in UI (e.g., bash-like terminal styling for command + stdout/stderr)
- Validate wrapper surface vs agent usage: ensure read_resource gating covers the agent’s built-in mcp__resources__read path, and decide whether list_resources ever needs "ask" in the future.
- Consider resource approval granularity (server-level vs URI/path patterns) as a follow-up; MVP uses server-level ask with URI displayed for context.
  - Abort individual tool calls: track gather() tasks per call_id; cancel selectively
  - Persist approvals to a small JSON file under logs/mini_codex/<agent>/run_*/ or a stable local app dir
- Phase 3
  - Multi-session support; auth; nicer UI; streaming tokens; richer keyboard mapping

Acceptance criteria
- With a policy that marks e.g. mcp__local__bash as "ask", the first model-issued call triggers an approval request. Clicking Deny makes ApprovalsProvider return deny; wrapper raises TurnAbortRequested; the agent logs a synthetic function_call_output + tool_error for the denied call, emits function_call_output for any other pending call_ids in that batch with an aborted error, and ends the turn. Clicking Allow executes the tool. Approval events approval_pending and approval_decision are visible in the transcript and via /ws (when UI-backed).
- With a policy that marks resource reads for server "local" as "ask", a read_resource(local, "/path") triggers the same approval flow; Deny ends the turn after all batch call_ids have been answered; Allow returns the real content.
- The UI shows live events, allows sending a new user message, and (when UI-backed) handles approvals. Headless runs can use an ApprovalsProvider that auto-returns allow.
- Hitting Abort during a pending model call returns control within ~1s and emits an "aborted" notification; server remains healthy and can start another run.
- Refreshing /transcript shows the full in-memory transcript of the current run so far.

Refinement: typed approvals events (no dicts; no agent coupling)
- Keep approvals optional and independent. The MiniCodex agent does not import or depend on approvals types, publishers, or hooks.
- Typed models only (no base class, no internal discriminator):
  - ApprovalRequested: call_id: UUID, mode: Literal["tool","resource_read"], tool: str|None, server: str|None, uri: str|None, args: dict[str, Any]|None, requested_at: datetime
  - ApprovalResolved: call_id: UUID, allowed: bool, resolved_at: datetime, reason: str|None
- Publisher protocol (typed, pluggable):
  - ApprovalsPublisher with methods:
    - on_requested(evt: ApprovalRequested) -> None
    - on_resolved(evt: ApprovalResolved) -> None
  - Default: NoopPublisher (headless). Optional adapters (e.g., JsonlApprovalsPublisher, UISocketApprovalsPublisher) serialize at the edge; core stays typed-only.
- Wrapper contract (no agent coupling):
  - ApprovalPolicyHandler(engine, hub) is injected into the agent; any UI bridge publishes pending approvals from ApprovalHub and resolves them. No manager wrapper required.
- Agent behavior (unchanged surface; minimal catch):
  - Agent catches TurnAbortRequested around call_tool/read_resource, emits synthetic function_call_output error for the denied call_id (and for remaining unprocessed call_ids in that batch), then ends the turn. This preserves the Responses invariant of exactly one function_call_output per tool_call. No approvals hooks in agent.
- Logging/storage separation:
  - Agent transcript remains via TranscriptLoggerHandler (typed agent events only).
  - ApprovalsPublisher owns its logs/bridges (e.g., approvals.jsonl, WebSocket UI); default path can co-locate under the same run_dir without mixing concerns.
- Tests (scoped):
  - Wrapper: ask → publishes typed requested/resolved events; deny → TurnAbortRequested; allow → delegate.
  - Agent: denial leads to one synthetic output per call_id and turn termination.

Future enhancements
- Should approvals be per-session or global? MVP: per-session with optional Save/Load.
- How to present resources/tools in UI compactly? MVP: only tools that appear get toggles; optionally fetch list at connect time.
- Backpressure if events are very chatty? MVP: drop oldest beyond N in UI; no server throttling yet.

Implementation notes (code pointers)
- Agent refactor: route all tool calls via mcp.call_tool(server, name, arguments) and resource reads via mcp.read_resource(server, uri); remove direct session.get + session.call_tool usage.
- Approvals gating is implemented by ApprovalPolicyHandler at the agent boundary.
- Abort turn on denial: define TurnAbortRequested(Exception) in approvals.py; wrapper raises it on deny; agent wraps mcp.call_tool/read_resource in try/except TurnAbortRequested, then:
  - Emits function_call_output for the denied call with a structured error payload, and tool_error for visibility.
  - Emits function_call_output with a minimal aborted/error payload for each remaining call_id in the same batch that hasn't been answered yet.
  - Ends the turn without re-sampling.
- Event forwarding is already in place via _emit_event(); UI-backed providers also send approval_pending/approval_decision to /ws.

Progress log
- 2025-09-14T00:00:00Z sha=6f2877fa: Drafted minimal design; next: implement approvals manager, add agent guard, scaffold FastAPI server and simple HTML UI.
- 2025-09-14T18:55:00Z sha=6f2877fa: Earlier draft used a manager wrapper for approvals; current implementation uses ApprovalPolicyHandler + ApprovalHub injected into the agent stack.
- 2025-09-14T19:20:00Z sha=6f2877fa: Revised abort-turn design to be UI-agnostic: introduce ApprovalsProvider and TurnAbortRequested; wrapper raises on deny; agent catches and ends the turn with synthetic events.

---

## Dev quickstart (UI) — two-server setup (recommended)

For local development, run Vite for the frontend and FastAPI for the backend, and proxy WebSocket traffic from Vite → FastAPI.

1) Add a WS proxy in src/adgn/agent/web/vite.config.ts:

```ts
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: { proxy: { '/ws': { target: 'http://127.0.0.1:8765', ws: true, changeOrigin: true } } },
  build: { outDir: '../server/static/web', emptyOutDir: true },
})
```

2) Start the backend (agent + FastAPI server):

```bash
direnv exec /Users/mpokorny/code/ducktape/adgn adgn-mini-codex serve --host 127.0.0.1 --port 8765
```

3) Start the frontend (Vite dev server):

```bash
npm --prefix /Users/mpokorny/code/ducktape/adgn/src/adgn/agent/web install
npm --prefix /Users/mpokorny/code/ducktape/adgn/src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173
```

4) Open http://127.0.0.1:5173. The UI connects to ws://127.0.0.1:5173/ws, which Vite proxies to the backend at 127.0.0.1:8765.

## Single-CLI (serve static assets)

If you prefer to serve the built UI from FastAPI (no Vite), build assets once and run the backend only:

```bash
# Build once
npm --prefix /Users/mpokorny/code/ducktape/adgn/src/adgn/agent/web install
npm --prefix /Users/mpokorny/code/ducktape/adgn/src/adgn/agent/web run build

# Start backend (serves /, /assets/*, /vite.svg from static/web)
direnv exec /Users/mpokorny/code/ducktape/adgn adgn-mini-codex serve --host 127.0.0.1 --port 8765
# Open http://127.0.0.1:8765
```

Notes
- The backend serves static from src/adgn/agent/server/static/web. Missing assets will 404 until you build.
- Vite dev server gives fast HMR during UI work; use single-CLI after you’re happy with the build.
- A future flag (e.g., `--build-web`) can auto-build assets on `serve` when missing.
