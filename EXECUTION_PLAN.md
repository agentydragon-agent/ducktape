# Execution Plan: Remaining Work from plan.md

## ASCII Execution Flow

```
                    ┌─────────────────────────────────────┐
                    │   WAVE A: Pre-Requisite Test Fixes  │
                    │        (3 parallel agents)          │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  WAVE B: Infrastructure Migration   │
                    │       (12 parallel agents)          │
                    │                                     │
                    │  ┌─────────────┐  ┌──────────────┐ │
                    │  │ HTTP→MCP    │  │  WebSocket   │ │
                    │  │  (8 tools)  │  │ Test Cleanup │ │
                    │  │             │  │  (4 files)   │ │
                    │  └─────────────┘  └──────────────┘ │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │    WAVE C: UI Layout Implementation  │
                    │         (8 parallel agents)         │
                    │                                     │
                    │  Timeline | PolicyPane | Composer   │
                    │  Layout   | Routing    | Badges     │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   WAVE D: Backend Feature Complete  │
                    │         (4 parallel agents)         │
                    │                                     │
                    │  AgentState | Approvals | LoopHooks│
                    │  Notify     | Proposals | Chat/UI  │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │    WAVE E: Code Quality Scans       │
                    │        (28 parallel agents)         │
                    │                                     │
                    │  [All scan prompts in prompts/scans/]│
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  WAVE F: Violation Analysis & Plan  │
                    │         (1 analysis agent)          │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │      WAVE G: Parallel Cleanup       │
                    │         (5 parallel agents)         │
                    │                                     │
                    │  Top violations by category         │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   WAVE H: Documentation & Verify    │
                    │         (6 parallel agents)         │
                    │                                     │
                    │  Docs | Misc Cleanups | Verification│
                    └─────────────────────────────────────┘

Total: 69 parallel task agent calls across 8 serial waves
```

## Wave A: Pre-Requisite Test Fixes (3 parallel)

**Dependencies**: None (blocking other work)

**Tasks**:
1. **ResponseUsage Fix** (13 tests)
   - Add `input_tokens_details`, `output_tokens_details` to match OpenAI SDK
   - Files: grep for `ResponseUsage` usage

2. **CallToolResult Fix** (3 tests)
   - Add `meta={}` parameter to match FastMCP API change
   - Files: grep for `CallToolResult` instantiation

3. **Event Loop Fixes** (20+ tests)
   - Convert to `@pytest.mark.asyncio` where missing
   - Fix `asyncio.Runner` usage patterns
   - Files: Tests that fail with event loop errors

## Wave B: Infrastructure Migration (12 parallel)

**Dependencies**: Wave A complete

### B1: HTTP → MCP Migration (8 parallel agents)

**Agent 1: Agent Lifecycle Tools**
- Implement `create_agent`, `delete_agent`, `boot_agent` in `mcp_bridge/servers/agents.py`

**Agent 2: MCP Config Tools**
- Implement `update_mcp_config`, `attach_server`, `detach_server`

**Agent 3: Execution Tools**
- Implement `prompt`, `abort_run` tools

**Agent 4: Approval Tools**
- Implement `deny_tool_call`, `deny_abort` tools (complement existing `approve_tool_call`)

**Agent 5: Policy Tools**
- Implement `set_policy`, `approve_proposal`, `reject_proposal` tools

**Agent 6: Agent Info Resource**
- Implement `resource://agents/{id}/info` (rich agent metadata)

**Agent 7: Snapshot Resource**
- Implement `resource://agents/{id}/snapshot` (compositor snapshot)

**Agent 8: Frontend Migration**
- Update frontend to use MCP tools instead of HTTP REST endpoints
- Update `features/agents/api.ts` to call MCP tools

### B2: WebSocket Test Cleanup (4 parallel agents)

**Agent 9: conftest.py Fixture**
- Update `/ws` → `/ws/session` in `tests/agent/conftest.py:347`
- Update `Envelope` → `ChannelEnvelope`

**Agent 10: agents_ws Tests (Part 1)**
- Fix first 5 tests in `tests/agent/server/test_agents_ws.py`

**Agent 11: agents_ws Tests (Part 2)**
- Fix remaining 5 tests in `tests/agent/server/test_agents_ws.py`

**Agent 12: Verify All WebSocket Tests**
- Run all WebSocket-related tests, verify fixes

## Wave C: UI Layout Implementation (8 parallel)

**Dependencies**: Wave B complete (needs MCP tools available)

**Agent 1: AgentTimeline Enhancement**
- Rename `ApprovalTimeline.svelte` → `AgentTimeline.svelte`
- Merge `UiDisplayItem[]` from `uiState` store
- Show approvals, tool calls, UI messages in unified timeline

**Agent 2: PolicyEditorPane Extraction**
- Extract from `ApprovalsPanel.svelte`
- Policy view/edit + proposals UI
- Component: `PolicyEditorPane.svelte`

**Agent 3: MessageComposer Completion**
- Complete `MessageComposer.svelte`
- Send messages, abort agent
- Only shown for local agents with UI server

**Agent 4: App.svelte Layout**
- CSS grid: `timeline | policy` + conditional composer
- Side-by-side layout per mockups

**Agent 5: MCP Subscriptions Wiring**
- Wire `resource://agents/{id}/approvals/history`
- Wire `resource://approval-policy/policy.py`
- Update components to use subscriptions

**Agent 6: UI Server Detection**
- Check `$agentStatus.ui?.ready`
- Conditional composer rendering
- Show UI messages in timeline

**Agent 7: Agent Mode Badge**
- Add [LOCAL] or [BRIDGE] badge
- Indicates agent loop presence
- UI server shown implicitly via composer/timeline

**Agent 8: Routing Updates**
- Global approvals view
- Agent selection routing
- Navigation between views

## Wave D: Backend Feature Complete (4 parallel)

**Dependencies**: Wave C complete

**Agent 1: Agent State Notifications**
- Wire `resource://agents/{id}/state` to emit `resource_updated` on:
  - User prompt, assistant message, tool call, approval decision
- Pattern: compositor/session events → `server.broadcast_resource_updated()`

**Agent 2: Approvals/Proposals HTTP + MCP**
- Add HTTP endpoint: `POST /api/agents/{id}/proposals {content}`
- Mount proposer/admin servers by default for live agents
- MCP tests: create→visible, withdraw→removed

**Agent 3: Loop Hooks + DB Server**
- Implement `loop.enable_hook/disable_hook` with `loop://hooks/{id}` resources
- Orchestrator bridge: coalesced notifications → hooks
- Read-only DB MCP server: `db://view/*`, `query` tool

**Agent 4: Chat/UI Delivery**
- Promote MCP-native chat inbox (`ui://chat/inbox`, `chat_read_since`)
- Runtime bridges: human chat notifications → `UiState`
- Assistant outputs → `chat.assistant.post`
- Remove legacy `ui` MCP server after migration

## Wave E: Code Quality Scans (28 parallel)

**Dependencies**: Wave D complete (all code in place)

Run each scan prompt from `prompts/scans/` in parallel:

1. api-model-design.md
2. asyncio-antipatterns.md
3. denormalized-computed-fields.md
4. duplicated-test-code.md
5. error-swallowing.md (NEW)
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

**Note**: Some scans may not apply to codebase (e.g., pygit2-patterns if no pygit2 usage)

## Wave F: Violation Analysis (1 agent)

**Dependencies**: Wave E complete (all scan results available)

**Task**: Analyze all scan results
- Aggregate findings by category
- Prioritize violations by severity/frequency
- Create cleanup plan for Wave G
- Identify top 5 categories for parallel cleanup

## Wave G: Parallel Cleanup (5 parallel)

**Dependencies**: Wave F complete (analysis done)

**Tasks**: Based on Wave F analysis, create 5 parallel cleanup agents targeting:
- Top violation category 1 (e.g., error-swallowing)
- Top violation category 2 (e.g., unnecessary-verbosity)
- Top violation category 3 (e.g., type-ignore-suppressions)
- Top violation category 4 (e.g., duplicated-test-code)
- Top violation category 5 (e.g., suspicious-nullability)

Each agent applies fixes for ~20-30 instances of their assigned pattern.

## Wave H: Documentation & Verification (6 parallel)

**Dependencies**: Wave G complete (cleanup done)

**Agent 1: MCP Runtime Documentation**
- Update docs after loop hooks + DB server land
- Document new MCP resources and tools

**Agent 2: Chat Inbox Architecture Docs**
- Document chat inbox architecture
- MCP-native chat delivery patterns

**Agent 3: Sandboxer/MCP Cross-References**
- Cross-reference seatbelt TODO in sandboxer/MCP docs
- Link related security considerations

**Agent 4: Plan.md Compression**
- Compress completed sections (reference code, not specs)
- Keep plan.md focused on remaining/future work

**Agent 5: Misc Cleanups**
- Seatbelt: structured findings, remove implicit trace write, CLI shim
- Rename `agents_ws.py`
- Inline `channels/endpoints.py`
- NotifyingFastMCP private attr replacements
- Remove named volume comments

**Agent 6: Final Verification**
- Run: `uv run ruff check . --fix`
- Run: `uv run python -m mypy adgn`
- Run: `pytest -q adgn/tests/agent`
- Verify all tests pass
- Verify no type errors
- Verify no linting errors

## Execution Strategy

### Parallelism
- Each wave runs all agents in **single message with multiple Task tool calls**
- Maximum parallelism within each wave
- Serial between waves (dependencies)

### Agent Configuration
- Use `model="haiku"` for straightforward scans/cleanups
- Use `model="sonnet"` for complex migrations/implementations
- Use `subagent_type="general-purpose"` for all agents

### Error Handling
- If any agent in a wave fails, review and fix before proceeding
- Some scans may report "no violations found" - this is success
- Test failures should be investigated and fixed

### Estimated Timeline
- Wave A: ~10 minutes (3 agents)
- Wave B: ~30 minutes (12 agents, complex migrations)
- Wave C: ~40 minutes (8 agents, UI work)
- Wave D: ~25 minutes (4 agents, backend features)
- Wave E: ~60 minutes (28 agents, all scans)
- Wave F: ~10 minutes (1 agent, analysis)
- Wave G: ~30 minutes (5 agents, cleanup)
- Wave H: ~25 minutes (6 agents, docs + verify)

**Total estimated time**: ~4 hours of agent work (with human review between waves)

## Success Criteria

### Wave A Success
- All 36+ test fixes applied
- Tests pass: `pytest tests/agent/`

### Wave B Success
- 18 new MCP tools/resources implemented
- Frontend migrated to MCP tools
- 10 WebSocket tests fixed
- All tests pass

### Wave C Success
- UI layout matches mockups
- AgentTimeline shows unified events
- PolicyEditorPane functional
- MessageComposer works for local+UI agents

### Wave D Success
- Agent state notifications working
- Proposals HTTP endpoint + MCP integration
- Loop hooks + DB server implemented
- Chat inbox fully MCP-native

### Wave E Success
- 28 scan reports generated
- Each report lists specific violations with file:line references

### Wave F Success
- Prioritized cleanup plan created
- Top 5 violation categories identified
- Specific fix strategies documented

### Wave G Success
- Top 5 violation categories fixed
- Tests still pass
- Type checking still passes

### Wave H Success
- Documentation updated
- All misc cleanups applied
- Final verification:
  - ✅ Ruff clean
  - ✅ Mypy clean
  - ✅ All tests pass

## Notes

### Deferred to Future
- WebSocket → MCP subscription migration (Phase 2)
  - Requires MCP subscription infrastructure fully reliable
  - Definition of Done documented in plan.md
- Svelte component test execution
  - Blocked by Svelte 6 + vitest incompatibility
  - 45 tests written, waiting for upstream fix
- E2E tests execution
  - Requires Docker daemon
  - 3 tests written, marked `@pytest.mark.requires_docker`

### Out of Scope
- Runs & Events endpoints (`/api/runs/*`)
  - Deferred until pagination/filtering design
- Agent status resource (`resource://agents/{id}/status`)
  - Deferred due to complex structure
- Server capabilities resource
  - Deferred as handshake helper
