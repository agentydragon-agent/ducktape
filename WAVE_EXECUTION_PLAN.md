# Maximally Parallel Wave Execution Plan

**Status**: Waves A-C complete, Wave D onwards remaining

**Strategy**: Execute each wave as a **single message with multiple parallel Task tool calls**. Wait for all agents in a wave to complete before starting the next wave.

**Agent Configuration**:
- `model="sonnet"` for complex migrations, implementations (Waves D1-D3, E1-E3)
- `model="haiku"` for scans, cleanups, simple routing (Waves F, G, H)
- `subagent_type="general-purpose"` for all

---

## Wave D1: Backend MCP Resources (8 parallel agents, ~3 hours)

**Dependencies**: Waves A-C complete (MCP infrastructure working)

**Execute in single message** with 8 Task tool calls:

### Agent 1: resource://agents/list + notifications
- Create `resource://agents/list` in agents MCP server
- Returns: Agent list with status, lifecycle, pending approvals (JSON)
- Wire notifications: Registry events (create/delete/status) → `broadcast_resource_updated("resource://agents/list")`
- Location: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py` + `adgn/src/adgn/agent/runtime/registry.py`
- Test: Read resource returns agent list, create agent triggers notification

### Agent 2: resource://agents/{id}/session/state + notifications
- Create `resource://agents/{id}/session/state`
- Returns: Session state, run state, transcript items (JSON)
- Wire notifications: Session events (user text, assistant text, tool call, result) → `broadcast_resource_updated()`
- Location: `agents.py` + `adgn/src/adgn/agent/runtime/session.py`
- Test: Read resource returns session state, sending prompt triggers notification

### Agent 3: resource://agents/{id}/approvals/pending + notifications
- Create `resource://agents/{id}/approvals/pending`
- Returns: Pending approvals list (JSON)
- Wire notifications: Approval hub events (request/decision) → `broadcast_resource_updated()`
- Location: `agents.py` + `adgn/src/adgn/agent/approvals/hub.py`
- Test: Read resource returns pending approvals, new approval triggers notification

### Agent 4: resource://agents/{id}/policy/state + notifications
- Create `resource://agents/{id}/policy/state`
- Returns: Policy content, id, proposals (JSON)
- Wire notifications: Policy engine events (policy update, proposal create) → `broadcast_resource_updated()`
- Location: `agents.py` + `adgn/src/adgn/agent/approvals/policy_engine.py`
- Test: Read resource returns policy, update policy triggers notification

### Agent 5: resource://agents/{id}/mcp/state + notifications
- Create `resource://agents/{id}/mcp/state`
- Returns: MCP servers sampling snapshot (JSON)
- Wire notifications: Compositor events (server attach/detach) → `broadcast_resource_updated()`
- Location: `agents.py` + `adgn/src/adgn/mcp/compositor/server.py`
- Test: Read resource returns sampling snapshot, attach server triggers notification

### Agent 6: resource://agents/{id}/ui/state + notifications
- Create `resource://agents/{id}/ui/state`
- Returns: UI state (if UI server attached) (JSON)
- Wire notifications: UI manager events (state change) → `broadcast_resource_updated()`
- Location: `agents.py` + `adgn/src/adgn/agent/runtime/ui_manager.py` (or equivalent)
- Test: Read resource returns UI state, UI update triggers notification

### Agent 7: resource://presets/list
- Create `resource://presets/list`
- Returns: Available agent presets (JSON)
- No notifications needed (presets don't change at runtime)
- Location: `agents.py`
- Test: Read resource returns presets list

### Agent 8: Backend tests for all new resources
- Add unit tests for all 7 new resources in `tests/agent/mcp_bridge/test_agents_server.py`
- Test resource read returns correct JSON structure
- Test notifications emit on events
- Test error handling (agent not found, invalid ID)
- Expected: ~20-30 new tests (3-5 per resource)

**Success Criteria**:
- All 7 MCP resources readable and return correct JSON
- All notification calls wired and emitting on events
- 20-30 new backend tests passing

---

## Wave D2: Frontend MCP Migration (9 parallel agents, ~3 hours)

**Dependencies**: Wave D1 complete (resources available)

**Execute in single message** with 9 Task tool calls:

### Agent 1: AgentsSidebar → MCP subscription
- Migrate `AgentsSidebar.svelte` to subscribe to `resource://agents/list`
- Replace WebSocket connection with MCP subscription
- Pattern: Subscribe → re-read on notification → update store
- Remove: WebSocket `/ws/agents` connection code
- Test: Manually verify agent creation updates sidebar without reload

### Agent 2: ChatPane → MCP subscription
- Migrate `ChatPane.svelte` to subscribe to `resource://agents/{id}/session/state`
- Replace WebSocket `/ws/session` with MCP subscription
- Show transcript items from resource
- Test: Manually verify sending prompt updates transcript without reload

### Agent 3: ApprovalsPanel → MCP subscription
- Migrate `ApprovalsPanel.svelte` to subscribe to `resource://agents/{id}/approvals/pending`
- Replace WebSocket `/ws/approvals` with MCP subscription
- Show pending approvals from resource
- Test: Manually verify approval request appears without reload

### Agent 4: PolicyEditorPane → MCP subscription + tools
- Migrate `PolicyEditorPane.svelte` to subscribe to `resource://agents/{id}/policy/state`
- Replace HTTP GET `/api/agents/{id}/policy` with MCP resource read
- Replace HTTP PUT `/api/agents/{id}/policy` with `set_policy` tool
- Replace HTTP POST `/api/agents/{id}/policy/proposals/{id}/approve` with `approve_proposal` tool
- Replace HTTP POST `/api/agents/{id}/policy/proposals/{id}/reject` with `reject_proposal` tool
- Test: Manually verify policy edit, proposal approve/reject work

### Agent 5: ServersPanel → MCP subscription
- Migrate `ServersPanel.svelte` to subscribe to `resource://agents/{id}/mcp/state`
- Replace WebSocket `/ws/mcp` with MCP subscription
- Show MCP servers from sampling snapshot
- Test: Manually verify server attach/detach updates panel without reload

### Agent 6: UI state handling → MCP subscription
- Migrate UI state code to subscribe to `resource://agents/{id}/ui/state`
- Replace WebSocket `/ws/ui` with MCP subscription
- Graceful degradation if UI server not attached
- Test: Manually verify UI messages appear when UI server attached

### Agent 7: MessageComposer → MCP tool
- Migrate `MessageComposer.svelte` to use `prompt` tool
- Replace HTTP POST `/api/agents/{id}/message` with `prompt` tool call
- Test: Manually verify sending message works

### Agent 8: ApprovalTimeline → MCP resource
- Migrate `ApprovalTimeline.svelte` to use `resource://agents/{id}/approvals/history`
- Replace HTTP GET `/api/agents/{id}/approvals/history` with MCP resource read
- Test: Manually verify history loads correctly

### Agent 9: Presets loading → MCP resource
- Migrate `listPresets()` in `api.ts` to use `resource://presets/list`
- Replace HTTP GET `/api/presets` with MCP resource read
- Test: Manually verify agent creation shows presets

**Success Criteria**:
- All 9 frontend components migrated to MCP
- No HTTP calls to `/api/agents/*` remain in frontend
- No WebSocket connections to `/ws/*` remain in frontend
- Manual testing confirms live updates work

---

## Wave D3: Backend Cleanup (6 parallel agents, ~2 hours)

**Dependencies**: Wave D2 complete (frontend no longer uses HTTP/WS)

**Execute in single message** with 6 Task tool calls:

### Agent 1: Delete WebSocket channels (session, approvals, policy)
- Delete `/ws/session` endpoint and `SessionChannelManager` class
- Delete `/ws/approvals` endpoint and `ApprovalsChannelManager` class
- Delete `/ws/policy` endpoint and `PolicyChannelManager` class
- Files: `adgn/src/adgn/agent/server/channels/session.py`, `approvals.py`, `policy.py`
- Remove imports and registrations from `app.py`
- Run: `grep -r "/ws/session\|/ws/approvals\|/ws/policy" adgn/src/adgn/agent/server/` to verify deletion

### Agent 2: Delete WebSocket channels (mcp, ui, agents)
- Delete `/ws/mcp` endpoint and `McpChannelManager` class
- Delete `/ws/ui` endpoint and `UiChannelManager` class
- Delete `/ws/agents` endpoint and `AgentsWSHub` class
- Files: `channels/mcp.py`, `channels/ui.py`, `agents_ws.py`
- Run: `grep -r "/ws/mcp\|/ws/ui\|/ws/agents" adgn/src/adgn/agent/server/` to verify deletion

### Agent 3: Delete channel infrastructure
- Delete `adgn/src/adgn/agent/server/channels/` directory entirely
- Delete channel bundle code (`bundle.py`, references to `_channel_bundle`)
- Remove all channel imports from `app.py`
- Run: `grep -r "_channel_bundle\|channel.bundle" adgn/` to verify deletion

### Agent 4: Delete HTTP endpoints (agent CRUD)
- Delete `/api/agents` POST (create), GET (list), GET `/{id}` (get), DELETE `/{id}` (delete)
- Delete `/api/agents/{id}/boot`, `/api/agents/{id}/prompt`, `/api/agents/{id}/abort`
- Delete `/api/agents/{id}/mcp` PATCH, `/api/agents/{id}/mcp/attach` POST, `/api/agents/{id}/mcp/detach` POST
- File: `adgn/src/adgn/agent/server/app.py`
- Run: `grep -r "POST.*api/agents\|GET.*api/agents\|DELETE.*api/agents" app.py` to verify deletion

### Agent 5: Delete HTTP endpoints (approvals, policy, misc)
- Delete `/api/agents/{id}/approve`, `/api/agents/{id}/deny_continue`, `/api/agents/{id}/deny_abort` POST endpoints
- Delete `/api/agents/{id}/policy` GET/PUT, `/api/agents/{id}/policy/proposals/{id}/approve` POST, `/api/agents/{id}/policy/proposals/{id}/reject` POST
- Delete `/api/agents/{id}/approvals/history` GET, `/api/agents/{id}/message` POST
- Delete `/api/presets` GET, `/api/capabilities` GET
- Run: `grep -r "api/agents.*policy\|api/presets\|api/capabilities" app.py` to verify deletion

### Agent 6: Update backend tests
- Fix WebSocket test fixtures using removed `/ws` endpoints
- Update 10 tests in `tests/agent/conftest.py:347`, `tests/agent/server/test_agents_ws.py:59`
- Change envelope format: `Envelope(session_id,...)` → `ChannelEnvelope(channel,...)` (or remove if obsolete)
- Run: `pytest tests/agent/ -v` to verify all tests pass

**Success Criteria**:
- ZERO WebSocket endpoints remain (`grep -r "/ws/" adgn/src/adgn/agent/server/` returns nothing)
- ZERO channel bundle references (`grep -r "_channel_bundle" adgn/` returns nothing)
- ZERO HTTP `/api/agents/*` endpoints remain (only `/`, `/health` remain)
- All backend tests pass

---

## Wave D4: E2E Tests Expansion (5 parallel agents, ~2 hours)

**Dependencies**: Wave D3 complete (all migrations done)

**Execute in single message** with 5 Task tool calls:

### Agent 1: MCP subscription live update tests
- Add E2E tests to `tests/agent/e2e/test_mcp_ui.py`
- Test: Create agent → verify appears in sidebar without page reload (check DOM)
- Test: Send approval → verify timeline updates without page reload
- Test: Update policy → verify policy editor updates without page reload
- Expected: 3-5 new Playwright tests

### Agent 2: Resource read error handling tests
- Add E2E tests for error scenarios
- Test: Read non-existent resource (agent not found) → verify 404 handled gracefully
- Test: Read malformed resource (invalid JSON) → verify error message shown
- Test: Resource read timeout → verify timeout message shown
- Expected: 3-5 new Playwright tests

### Agent 3: Concurrent subscription tests
- Add E2E tests for concurrent scenarios
- Test: Multiple agents, rapid status changes → verify all updates received
- Test: Subscribe/unsubscribe/resubscribe → verify state consistency
- Test: Agent deleted while subscribed → verify graceful cleanup
- Expected: 3-5 new Playwright tests

### Agent 4: Performance and load tests
- Add E2E tests for performance
- Test: 100+ pending approvals → verify UI remains responsive
- Test: High-frequency updates (10+ per second) → verify no missed updates
- Test: Many concurrent subscriptions (10+ agents) → verify all work
- Expected: 3-5 new Playwright tests

### Agent 5: Edge case tests
- Add E2E tests for edge cases
- Test: Network interruption during resource read → verify retry/error handling
- Test: MCP server disconnect/reconnect → verify subscription recovery
- Test: Subscription to non-existent resource URI → verify error handling
- Expected: 3-5 new Playwright tests

**Success Criteria**:
- 15-25 new E2E tests added
- All E2E tests pass (requires Docker + Playwright)
- Coverage includes subscriptions, errors, concurrency, performance, edge cases

---

## Wave E: Token-Based Connection Routing (1 agent, ~2 hours)

**Dependencies**: Wave D4 complete (optional - can be separate wave)

**Execute as single Task tool call**:

### Agent 1: Implement token-based routing
- Create `MCPRoutingHandler` ASGI app at `/mcp` endpoint
- Define `TokenRole` enum (HUMAN, AGENT)
- Extract Bearer token from Authorization header
- Look up token in table: `{role: "human" | "agent", agent_id?: str}`
- Route based on role using `StreamableHTTPSessionManager`:
  - AGENT role (with agent_id) → Route to agent's compositor MCP server
  - HUMAN role → Route to agents management MCP server
- Pattern: Custom ASGI app → token lookup → get/create session manager → `manager.handle_request()`
- Test: Agent token connects to compositor, human token connects to management server
- Location: `adgn/src/adgn/agent/server/app.py` or new `mcp_routing.py` file

**Success Criteria**:
- Single `/mcp` endpoint routes connections to correct backend
- Agent tokens access compositor (agent-facing tools)
- Human tokens access management server (human-facing tools)
- No prefixes needed - transparent proxy

---

## Wave F: Code Quality Scans (30 parallel agents, ~2 hours)

**Dependencies**: Wave E complete (all code in final state)

**Execute in single message** with 30 Task tool calls (use haiku model):

Launch scan agents for each prompt in `prompts/scans/`:

1. api-model-design.md
2. asyncio-antipatterns.md
3. denormalized-computed-fields.md
4. duplicated-test-code.md
5. error-swallowing.md
6. fastmcp-documentation-patterns.md
7. functional-over-imperative.md
8. identifier-naming.md
9. library-type-misuse.md
10. manual-serde-needs-pydantic.md
11. methods-vs-freestanding.md
12. missing-dataclass-pydantic.md
13. mypy-appeasing-code.md
14. overly-loose-typing.md
15. pydantic-antipatterns.md
16. pygit2-patterns.md
17. pytest-tmp-paths.md
18. stringly-typed.md
19. suspicious-defaults.md
20. suspicious-nullability.md
21. test-assertions.md
22. timestamp-naming.md
23. trivial-forwarder-methods.md
24. trivial-forwarders.md
25. type-ignore-suppressions.md
26. unnecessary-verbosity.md
27. useless-comments-and-docs.md
28. useless-documentation.md
29. useless-test-classes.md
30. walrus-get-pattern.md

Each agent:
- Read scan prompt from `prompts/scans/`
- Search codebase for violations
- Generate report with file:line references
- Save report to `scan_results/{scan_name}.md`

**Success Criteria**:
- 30 scan reports generated in `scan_results/`
- Each report lists violations with file:line references
- Some scans may return "no violations found" (that's okay)

---

## Wave G: Violation Analysis (1 agent, ~30 min)

**Dependencies**: Wave F complete (all scans done)

**Execute as single Task tool call** (use sonnet model):

### Agent 1: Analyze scan results
- Read all 30 reports from `scan_results/`
- Aggregate findings by category and severity
- Count violations per category
- Prioritize by frequency and impact
- Identify top 5 categories for Wave H cleanup
- Create cleanup strategy for each category
- Save analysis to `VIOLATION_ANALYSIS.md`

**Success Criteria**:
- Analysis document created
- Top 5 violation categories identified
- Cleanup strategies documented for each
- Estimated effort per category

---

## Wave H: Parallel Cleanup (5 parallel agents, ~2 hours)

**Dependencies**: Wave G complete (analysis done)

**Execute in single message** with 5 Task tool calls (use sonnet model):

Based on Wave G analysis, launch 5 cleanup agents targeting top violation categories.

### Agent 1: Top violation category 1
- Read category from `VIOLATION_ANALYSIS.md`
- Fix ~20-30 instances
- Run tests after each fix batch (every 5-10 fixes)
- Ensure no regressions

### Agent 2: Top violation category 2
- Fix ~20-30 instances
- Run tests after each fix batch
- Ensure no regressions

### Agent 3: Top violation category 3
- Fix ~20-30 instances
- Run tests after each fix batch
- Ensure no regressions

### Agent 4: Top violation category 4
- Fix ~20-30 instances
- Run tests after each fix batch
- Ensure no regressions

### Agent 5: Top violation category 5
- Fix ~20-30 instances
- Run tests after each fix batch
- Ensure no regressions

**Success Criteria**:
- Top 5 violation categories cleaned up
- All tests still pass
- Type checking still passes
- No new violations introduced

---

## Wave I: Documentation & Misc Cleanups (6 parallel agents, ~1 hour)

**Dependencies**: Wave H complete (cleanup done)

**Execute in single message** with 6 Task tool calls (use haiku model):

### Agent 1: MCP Runtime Documentation
- Update docs after Wave D migrations complete
- Document new MCP resources: `agents/list`, `agents/{id}/session/state`, etc.
- Document subscription pattern for frontend
- Update architecture diagrams
- Location: `adgn/docs/` or similar

### Agent 2: Chat Inbox Architecture Docs
- Document MCP-native chat inbox architecture
- Document `ui://chat/inbox`, `chat_read_since` patterns
- Cross-reference with UI server docs
- Location: `adgn/docs/`

### Agent 3: Sandboxer/MCP Cross-References
- Cross-reference seatbelt TODO in sandboxer docs
- Link MCP security considerations
- Document security boundaries
- Location: `adgn/docs/`

### Agent 4: Plan.md Compression
- Compress completed sections in `plan.md`
- Move detailed specs to code references
- Keep plan.md focused on future work
- Archive completed wave details to `COMPLETED_WAVES.md`

### Agent 5: Misc Cleanups
- Seatbelt: structured findings, remove implicit trace write, CLI shim
- Rename `agents_ws.py` to appropriate name (determine name based on new functionality)
- Inline `channels/endpoints.py` (too thin, only 17 lines)
- NotifyingFastMCP: replace private attr overrides with public hooks if available
- Remove named volume comments

### Agent 6: Type Hint Migration
- Replace `agent_id: str` with `agent_id: AgentID` throughout codebase
- Pattern: `grep -r "agent_id.*: str" adgn/src/adgn/agent/ | grep "def "`
- Update ~50 occurrences in mcp_bridge, server, runtime modules
- Update callers to use `AgentID(agent_id_string)` when converting
- Verify: `uv run python -m mypy adgn`

**Success Criteria**:
- Documentation updated for all new features
- Misc cleanups applied
- Type hints migrated to AgentID
- All cleanups committed

---

## Wave J: Final Verification (1 agent, ~30 min)

**Dependencies**: Wave I complete (everything done)

**Execute as single Task tool call** (use haiku model):

### Agent 1: Final verification
- Run: `uv run ruff check . --fix`
- Run: `uv run python -m mypy adgn`
- Run: `pytest -q adgn/tests/agent`
- Run: `cd adgn/src/adgn/agent/web && npm test`
- Verify all tools pass
- Generate final status report
- Save to `FINAL_VERIFICATION.md`

**Success Criteria**:
- ✅ Ruff clean (no linting errors)
- ✅ Mypy clean (no type errors)
- ✅ All pytest tests pass
- ✅ All npm tests pass
- Final report generated

---

## Summary: Execution Sequence

| Wave | Agents | Time | Model | Description |
|------|--------|------|-------|-------------|
| D1 | 8 | ~3h | sonnet | Backend MCP resources + notifications |
| D2 | 9 | ~3h | sonnet | Frontend MCP migration |
| D3 | 6 | ~2h | sonnet | Backend cleanup (delete HTTP/WS) |
| D4 | 5 | ~2h | sonnet | E2E tests expansion |
| E | 1 | ~2h | sonnet | Token-based routing |
| F | 30 | ~2h | haiku | Code quality scans |
| G | 1 | ~30m | sonnet | Violation analysis |
| H | 5 | ~2h | sonnet | Parallel cleanup (top 5 categories) |
| I | 6 | ~1h | haiku | Documentation + misc cleanups |
| J | 1 | ~30m | haiku | Final verification |

**Total**: 72 agents across 10 waves, ~18 hours of agent work

**Human Review Points**: After each wave completes, review agent outputs before starting next wave

---

## Execution Commands

### Wave D1 (8 agents in parallel)
```
Launch 8 Task tool calls in single message, each creating one backend MCP resource + notification wiring
```

### Wave D2 (9 agents in parallel)
```
Launch 9 Task tool calls in single message, each migrating one frontend component to MCP
```

### Wave D3 (6 agents in parallel)
```
Launch 6 Task tool calls in single message, each deleting a subset of HTTP/WebSocket infrastructure
```

### Wave D4 (5 agents in parallel)
```
Launch 5 Task tool calls in single message, each adding E2E tests for different scenarios
```

### Wave E (1 agent)
```
Launch 1 Task tool call implementing token-based connection routing
```

### Wave F (30 agents in parallel)
```
Launch 30 Task tool calls in single message, each running one code quality scan
```

### Wave G (1 agent)
```
Launch 1 Task tool call analyzing all scan results
```

### Wave H (5 agents in parallel)
```
Launch 5 Task tool calls in single message, each cleaning up one violation category
```

### Wave I (6 agents in parallel)
```
Launch 6 Task tool calls in single message, each handling documentation or misc cleanup
```

### Wave J (1 agent)
```
Launch 1 Task tool call running final verification
```

---

## Notes

1. **Maximize parallelism**: Each wave's agents are independent - launch all in one message
2. **Use appropriate model**: Sonnet for complex work (D1-D4, E, G, H), Haiku for simple work (F, I, J)
3. **Review between waves**: Human reviews agent outputs before proceeding to next wave
4. **Test frequently**: Agents should run tests after making changes
5. **Commit incrementally**: Each agent should commit its changes before reporting completion
