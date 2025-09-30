# MiniCodex UI/Protocol Migration Checklist

## Done
- [x] WebSocket protocol uses envelope + payload; all ServerMessage variants are Pydantic unions (discriminator "type")
- [x] Inbound WS commands validated via Pydantic discriminated union (HelloIn | ResumeIn | GetSnapshotIn | SendIn | ApproveIn | DenyIn | AbortIn | PingIn)
- [x] Removed string switches (typ == "...") in favor of isinstance over Pydantic classes
- [x] Approval decisions are protocol-native and distinct from handler actions:
  - [x] ApprovalDecision = approve | deny_continue | deny_abort (no reason field)
  - [x] ApprovalDecisionEvt embeds the exact ApprovalDecision
- [x] Server maps ApprovalDecision → handler action:
  - [x] approve → ContinueDecision()
  - [x] deny_continue → BypassToolInjectOutput(result=CallToolResult with {"ok": false, "error": "User denied: <call_id>"})
  - [x] deny_abort → AbortTurnDecision()
  - [x] No fallback: unknown decision raises TypeError
- [x] Approval manager emits ApprovalPendingEvt then ApprovalDecisionEvt (with embedded decision object)
- [x] Snapshot carries structured sampling: McpManager.SamplingSnapshot + mcp_servers: [McpServerInfo]
- [x] CLI loads only from .mcp.json (or MCP_CONFIG), no default local-exec; prints enabled servers on startup
- [x] UI JS extracted to static/app.js; unwraps envelope.payload; renders args_json; no swallowed exceptions
- [x] Tool output rule in agent: structuredContent → JSON; single TextContent → raw text; else JSON blocks
- [x] Avoid getattr for session/agent fields in server; use direct fields
- [x] Tests updated and passing for WS plain assistant text and WS tool multi-turn
- [x] Svelte + TypeScript + Vite scaffolded at src/adgn/agent/ui/web; build targets static/web; index route serves static/web/index.html if present

- [x] Snapshot sent on hello; includes transcript; UI restores transcript on reload
- [x] Server persists transcript (UserText/AssistantText/ToolCall/FunctionCallOutput) for snapshots
- [x] Snapshot schema fixed (Snapshot is BaseModel payload, not Envelope)
- [x] UI layout: full‑page chat with bottom composer; right sidebar with WS status and MCP servers
- [x] Client WS diagnostics: onerror/onclose show banner and console logs
- [x] Serve: agent + MCP created on uvicorn loop via app.state.agent_factory (single event loop)
- [x] Renamed AggregatingController → Reducer across code/tests/docs

## Pending
- [ ] Frontend: implement UI handling for approval decisions
  - [ ] approve: remove pending item; add transcript note
  - [ ] deny_continue: remove pending item; show injected function_call_output preview from decision mapping
  - [ ] deny_abort: remove pending item; add transcript “aborted” note
- [ ] Add e2e test for approval path: pending → approve/deny_continue/deny_abort → expected transcript and agent behavior
- [ ] Remove legacy static/index.html once feature parity is reached with Svelte app
- [ ] Document .mcp.json shapes accepted by CLI (stdio/sse), and examples under docs/
- [ ] Lint/type-check sweep for Pydantic discriminators and imports across protocol/server
- [ ] Ensure no leftover DTOs: remove any obsolete Decision* protocol classes
- [ ] CI: add UI build step (vite build) and assert static/web artifacts present
- [ ] Error surfacing: ensure UI shows protocol error events consistently (ErrorEvt)
