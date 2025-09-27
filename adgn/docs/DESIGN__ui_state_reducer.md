# UI State Reducer Refactor — Plan

Motivation
- Eliminate split of display logic between server and client and the confusion around multiple “transcripts”
- Make UI rendering deterministic, reloadable, and versioned
- Centralize transformation from agent/tool events → display items in one place (server-side)

Goals (acceptance criteria)
- Server maintains a single authoritative UiState per agent/session
- UiState is a typed, display‑oriented model; client renders only UiState (no own grouping)
- Ordering: ToolCall → FunctionCallOutput → grouped UI items emitted deterministically
- Snapshot reload: full UiState restored on reload with identical visual content
- End‑turn controlled via bus and reflected in UiState (no parsing of names)
- Protocol versioning for UiState messages (future‑proof)

Non‑Goals (for this refactor)
- Streaming deltas (we can start with whole‑state updates)
- Multi‑session persistence beyond a single server process lifetime

Design overview
- Server‑side reducer
  - A pure reducer reduce_ui_state(prev: UiState, evt: UiEvent) -> UiState consumes typed events and returns a new state
  - One source of truth lives on AgentSession: session.ui_state (not “transcript”)
- Display items (normalized)
  - UserMessage {id, ts, text}
  - AssistantMarkdown {id, ts, md}
  - ToolGroup {id, ts, tool: name, call_id, cmd?, approvals: [approve/deny_*], stdout, stderr, exit_code}
- Event inputs for reducer
  - UserText (on_user_text_event)
  - ToolCall (on_tool_call_event)
  - FunctionCallOutput (on_function_call_output_event)
  - ApprovalDecision (approval_decision)
  - UiMessage (from ui.send_message)
  - EndTurn (from ui.end_turn)
- MCP UI server & bus
  - ui.send_message(UiMessage) pushes UiMessage to per‑agent UiBus
  - ui.end_turn() pushes UiEndTurn; UiAutoHandler consumes via bus and Abort()s turn
  - Server drains UiBus items after tool outputs and before snapshot to generate UiMessage events into UiState
- Protocol
  - UiStateSnapshot { type: "ui_state_snapshot", v: "ui_state_v1", seq, state }
  - UiStateUpdated  { type: "ui_state_updated",  v: "ui_state_v1", seq, state } (initially whole state; optional future deltas)
  - Deprecate snapshot.transcript over time (keep for migration)

Ordering & snapshot
- After each FunctionCallOutput, reduce with any UiMessage items drained from UiBus → emit UiStateUpdated
- On hello/resume: drain UiBus, then send UiStateSnapshot of current UiState

Handler & loop control
- UiAutoHandler(bus):
  - on_before_sample: if bus.consume_end_turn() → Abort(); else Continue(RequireAny()) to force tool usage
  - before_tool_call: ContinueDecision (no per‑tool interception)
  - Reducer is applied by the UI server ConnectionManager/AgentSession on typed events and bus drains

Migration plan
1) Add UiState models and reducer, introduce UiStateSnapshot/Updated protocol (keep existing messages)
2) Server: create UiState on session, apply reducer on events; send UiStateUpdated after each change; include UiStateSnapshot on hello/resume
3) UI: implement UiState rendering path and remove legacy transcript path
4) UI: render only UiState; remove client-side grouping logic entirely

Testing
- Unit: reducer tests (tool grouping, approvals merge, stdout/stderr/exit code paths, multiple consecutive tool groups, end‑turn)
- Integration: run a full turn and assert UiState items sequence; reload → UiStateSnapshot matches

Decisions (resolved)
- DisplayItem schema: UserMessage, AssistantMarkdown, ToolGroup (no UiNotice for now)
- Approvals in ToolGroup: store full ApprovalDecision kind (approve | deny_continue | deny_abort)
- UiStateUpdated payload: send full state (v1)
- Persistence: in-memory only for now; TODO durable persistence later
- Assistant messages: only via ui.send_message; assistant_text path in UI mode MUST raise/crash with explanatory comment and pointers to the new path
- Protocol naming: ui_state_snapshot/ui_state_updated with version ui_state_v1
- Client: do not keep legacy transcript rendering; remove it

Risks & mitigations
- Drift between event stream and UiState: mitigated by single reducer and strictly ordered application
- Client/server mismatch during migration: version messages and feature flag on client

Execution checklist
- [ ] Define UiState and DisplayItem models (src/adgn/llm/mini_codex/ui/state.py)
- [ ] Implement pure reducer (src/adgn/llm/mini_codex/ui/reducer.py) + unit tests
- [ ] Extend protocol with UiStateSnapshot/UiStateUpdated (ui/protocol.py) + version constant
- [ ] Server: create session.ui_state; apply reducer on UserText/ToolCall/FunctionCallOutput/ApprovalDecision
- [ ] Server: drain UiBus after function outputs and before snapshot; reduce UiMessage into AssistantMarkdown items; emit UiStateUpdated
- [ ] Server: send UiStateSnapshot on hello/resume
- [ ] UI: render UiState only; map DisplayItem variants to components (UserMessage, AssistantMarkdown, ToolGroup)
- [ ] Remove legacy transcript path and client-side grouping (seatbelt)
- [ ] Server: in UI mode, crash on assistant_text path with explanatory comment (deprecation) and TODO to remove remaining code paths
- [ ] Cleanup: remove transcript usage in protocol and code; update docs

Appendix: example UiState (v1)
```json
{
  "seq": 5,
  "items": [
    { "kind": "UserMessage", "ts": "...", "text": "run ls -la" },
    { "kind": "ToolGroup", "ts": "...", "tool": "mcp__seatbelt__sandbox_exec", "call_id": "abc", "cmd": "ls -la", "approvals": ["approve"], "stdout": "...", "stderr": "", "exit_code": 0 },
    { "kind": "AssistantMarkdown", "ts": "...", "md": "Here are the results..." }
  ]
}
```