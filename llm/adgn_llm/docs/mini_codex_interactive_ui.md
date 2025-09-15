# MiniCodex interactive UI and approvals — minimal design

Author: Rai (@agentydragon)
Date: 2025-09-14
Repo path: llm/adgn_llm
sha=6f2877fa

Scope and goals
- Add a small HTTP UI for MiniCodex to:
  - Gate selected MCP tools behind explicit user approval. If not approved, synthesize a rejection tool result and continue the loop so the user can instruct next steps.
  - Provide a basic compose textarea with common keyboard shortcuts (Shift+Enter for newline; Cmd/Ctrl+Enter to send).
  - Allow aborting an in-flight rollout while the model call is pending (and later, allow aborting tool calls).
- Keep changes minimal and local to mini_codex; leverage existing event plumbing.
- Out of scope (for this iteration): multi-session management, auth, any persistence outside process, streaming token UI, prompt optimization/inop integration.

Current state (quick map)
- Agent loop: src/adgn_llm/mini_codex/agent.py:249–521 controls a turn. Tool calls are collected, then executed in parallel via asyncio.gather in _invoke() wrappers.
- Event emission: agent emits dict events via _emit_event(); handlers exist for both legacy dict and typed events.
  - Aggregating controller/handlers: src/adgn_llm/mini_codex/aggregating_handler.py
  - Transcript logger: src/adgn_llm/mini_codex/loggers.py
- Tool call execution:
  - ResponseFunctionToolCall objects are parsed (agent.py:332–356) and executed in _invoke (agent.py:380–424) and the sequential tail (agent.py:440–504).
  - Results are emitted via _emit_tool_result (agent.py:598–624), which also emits a "tool_error" event when parsed_error is present.
- No UI/server exists today; DisplayEventsHandler used by inop runner prints to console.

Design overview
We add three minimally-coupled pieces:
1) Approvals proxy around MCP (modular): a wrapper around McpManager/Sessions that enforces a hardcoded policy ("allow" or "ask"). For "ask", it emits a pending-approval event and awaits a UI decision; deny synthesizes a structured failure result and continues.
2) Lightweight HTTP UI (FastAPI+WebSocket) to:
   - Show transcript/events and pending tool calls.
   - Allow the user to send a message, toggle pre-approvals per tool, and abort the active run.
3) Abort controller: run the agent turn in an asyncio.Task and cancel it on user request; track and cancel per-tool tasks in Phase 2.

Component details
1) Approvals proxy (modular, not tightly coupled)
- New module: src/adgn_llm/mini_codex/approvals.py
- Models
  - Modes: only "allow" and "ask" (no "block" for now)
  - ToolKey: str = namespaced tool name "mcp__{server}__{tool}" (existing naming)
  - Policy: hardcoded Python function tool_policy(tool_key: str) -> Literal["allow","ask"]; no config/overrides yet.
- Proxy classes
  - class ApprovalHub: in-memory registry of pending approvals; exposes await_decision(call_id, tool_key, args) and resolve(call_id, allow: bool)
  - class McpManagerWithApprovals: wraps an underlying McpManager; decorates call_tool(server,name,args) and read_resource(server,uri). For call_tool, consult tool_policy; if "ask", emit approval_pending and await ApprovalHub; deny → return synthetic {ok:false,error:"User denied: <name>"}; allow → delegate to inner. For read_resource, use a virtual key (e.g., resource_read::{server}) and similar flow.
- Resources and approvals (note for MVP/follow‑up)
  - The agent uses both tools and resources (mcp__resources__list/read and manager.read_resource()). The wrapper should also gate resource reads.
  - Minimal approach: treat resource read as a virtual key like "resource_read::{server}" (include {uri} in the pending event payload for context). Policy can say ask/allow at server granularity; UI shows the exact URI before approving.
  - list_resources() stays allow; read_resource(server, uri) consults policy and, if "ask", emits approval_pending {kind:"approval_pending", call_id, type:"resource_read", server, uri} and awaits a decision.
- Agent integration
  - No changes to agent loop required; pass McpManagerWithApprovals into MiniCodex.create instead of bare McpManager.
- Minimal UX: When a tool or resource read is "ask", the UI shows a Pending Approvals item with Allow/Deny (including server/uri for resources); that specific call blocks until decision, then proceeds (deny → synthetic error, allow → execute).

2) HTTP UI server
- New package: src/adgn_llm/mini_codex/ui/
  - server.py: FastAPI app + WebSocket; minimal single-session state for now.
  - static/index.html: Simple page with:
    - Transcript pane (append-only),
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
        - {type: "send", text: "..."} -> appends a user message and triggers agent.sample() or agent.run(text)
        - {type: "approve", call_id: string} / {type: "deny", call_id: string} -> resolve a pending approval in ApprovalHub
        - {type: "abort"}
  - Keyboard shortcuts: In index.html, attach keydown listener for Cmd/Ctrl+Enter to send; Shift+Enter inserts newline (browser default).
- Launch entrypoint (optional now): small CLI to run the server, eg: adgn-mini-codex-ui --port 8765

3) Abort model rollout
- Session.run() creates an asyncio.Task for agent.run(); store ref.
- Abort path:
  - Cancel the task; if the cancellation happens during _responses_create_with_retry awaiting the OpenAI call, asyncio.CancelledError will propagate; server catches and emits "aborted".
  - In Phase 2, track per-tool gather() tasks and cancel them similarly.
- No agent-level changes are required for Phase 1 if we only cancel the outer task; the OpenAI client awaits will respond to task cancellation.

Wire-up and minimal code edits

Agent-awareness guarantee (opt-in wrapper)
- MiniCodex only depends on an McpManager-like interface; passing the approvals wrapper is optional. If you pass the plain McpManager, behavior is unchanged and the agent remains unaware of approvals.
- The wrapper preserves the same surface (list_tools, list_resources, read_resource, call_tool[server,name,args]). No conditionals in the agent; no interception unless you instantiate the wrapper.
- Minimal protocol sketch (preferred surface):
  - McpManagerProtocol: list_tools() -> list[dict], list_resources(only: list[str]|None=None) -> list[dict], read_resource(server: str, uri: str) -> Any, call_tool(server: str, name: str, arguments: dict[str, Any]) -> Any
- Example wiring:
  - base = McpManager(slots)
  - mcp = McpManagerWithApprovals(base, approval_hub, tool_policy)  # or just use base
  - await MiniCodex.create(..., mcp=mcp, ...)

API stubs (for clarity; implementation follows these shapes)
```python
from typing import Protocol, Any

class McpManagerProtocol(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...
    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> Any: ...

class ApprovalHub:
    async def await_decision(self, call_id: str, payload: dict[str, Any]) -> bool: ...
    def resolve(self, call_id: str, allow: bool) -> None: ...

class McpManagerWithApprovals(McpManagerProtocol):
    def __init__(self, inner: McpManagerProtocol, hub: ApprovalHub, tool_policy): ...
    # delegates list_tools, list_resources; gates read_resource and call_tool
    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> Any: ...
    async def read_resource(self, server: str, uri: str) -> Any: ...
```

- Small agent refactor: switch to manager-level call_tool/read_resource; no approvals-specific logic in agent. Passing a plain McpManager or the approvals wrapper both satisfy the same protocol, so the agent remains unaware.
- New modules
  - src/adgn_llm/mini_codex/approvals.py (policy/state/manager)
  - src/adgn_llm/mini_codex/ui/server.py (FastAPI app)
  - src/adgn_llm/mini_codex/ui/static/index.html (dumb UI)
- No changes to AggregatingController/handlers in Phase 1.

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
  - Approvals wrapper (McpManagerWithApprovals) + minimal UI glue
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
- With a policy that marks e.g. mcp__local__bash as "ask", the first model-issued call pauses and appears in Pending Approvals. Clicking Deny cancels the current agent turn immediately (no further tool execution); control returns to the user. Clicking Allow executes the tool. Approval events approval_pending and approval_decision are visible in the transcript and via /ws.
- With a policy that marks resource reads for server "local" as "ask", a read_resource(local, "/path") pauses with a Pending Approval showing the exact URI; Deny cancels the current agent turn; Allow returns the real content.
- The UI shows live events, allows sending a new user message, and toggling a tool to allowed (preapproval) so subsequent calls succeed.
- Hitting Abort during a pending model call returns control within ~1s and emits an "aborted" notification; server remains healthy and can start another run.
- Refreshing /transcript shows the full in-memory transcript of the current run so far.

Future enhancements
- Should approvals be per-session or global? MVP: per-session with optional Save/Load.
- How to present resources/tools in UI compactly? MVP: only tools that appear get toggles; optionally fetch list at connect time.
- Backpressure if events are very chatty? MVP: drop oldest beyond N in UI; no server throttling yet.

Implementation notes (code pointers)
- Agent refactor: route all tool calls via mcp.call_tool(server, name, arguments) and resource reads via mcp.read_resource(server, uri); remove direct session.get + session.call_tool usage.
- Approvals gating is entirely in McpManagerWithApprovals; no approval logic in the agent.
- Event forwarding is already in place via _emit_event(); UI subscribes to these along with approval_pending/approval_decision.

Progress log
- 2025-09-14T00:00:00Z sha=6f2877fa: Drafted minimal design; next: implement approvals manager, add agent guard, scaffold FastAPI server and simple HTML UI.
