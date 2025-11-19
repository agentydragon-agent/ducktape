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
   - Fix `asyncio.Runner` usage patterns (misuse causing test failures)
   - **Note**: `@pytest.mark.asyncio` decorators NOT needed - `asyncio_mode = "auto"` already configured in pyproject.toml
   - Files: Tests that fail with event loop errors (actual async/await issues, not missing decorators)

## Wave B: Infrastructure Migration (12 parallel)

**Dependencies**: Wave A complete

### B1: HTTP → MCP Migration (8 parallel agents)

**ARCHITECTURE NOTE**: Cross-agent tools are **thin routing wrappers** over existing single-agent MCP servers. DO NOT reimplement business logic - delegate to per-agent servers via compositor.get_child_client() or Python APIs.

**Agent 1: Agent Lifecycle Tools** (~30 min - 3 tools, straightforward routing)
- Implement `create_agent(preset, system?)`, `delete_agent(id)`, `boot_agent(id)`
- Route to registry.create_agent(), registry.remove_agent(), registry.ensure_live()
- **Complexity**: Low - registry methods already exist, just wrap with MCP tool decorator
- **Estimated LOC**: ~40 lines (3 tools × ~10 lines each + docstrings + models)

**Agent 2: MCP Config Tools** (~30 min - 3 tools, compositor Python API)
- Implement `update_mcp_config(id, config)`, `attach_server(id, name, spec)`, `detach_server(id, name)`
- Route to per-agent compositor.reconfigure(), mount_server(), unmount_server()
- Pattern: `infra = await registry.get_infrastructure(AgentID(agent_id)); await infra.compositor.mount_server(...)`
- **Complexity**: Low - compositor Python API is stable and well-tested
- **Estimated LOC**: ~45 lines (3 tools × ~12 lines each + error handling + models)

**Agent 3: Execution Tools** (~20 min - 2 tools, one alias + one routing)
- Implement `prompt(id, text)` - route to per-agent chat.human.post tool
- Implement `abort_run(id)` - **alias for existing `abort_agent`** or just documentation update
- **Complexity**: Very Low - `abort_agent` already exists (agents.py:364), `prompt` is thin routing to chat server
- **Estimated LOC**: ~25 lines (1 new tool + 1 alias/doc update + models)

**Agent 4: Approval Tools** (~25 min - 2 tools, one alias + one new)
- Implement `deny_tool_call(id, call_id, reason)` - **alias for `reject_tool_call`** with better naming
- Implement `deny_abort(id, call_id, reason)` - route to approval_hub.resolve(AbortTurnDecision)
- **Complexity**: Low - approval_hub API already used in existing tools
- **Estimated LOC**: ~30 lines (1 alias + 1 new tool + models)
- **Note**: `approve_tool_call` and `reject_tool_call` already exist (agents.py:346,355)

**Agent 5: Policy Tools** (~35 min - 3 tools, get_child_client routing)
- Implement `set_policy(id, content)`, `approve_proposal(id, proposal_id)`, `reject_proposal(id, proposal_id)`
- Route to per-agent approval_policy_admin server tools via get_child_client()
- Pattern: `client = infra.compositor.get_child_client("approval_policy_admin"); await client.call_tool("approve_proposal", {"id": proposal_id})`
- **Complexity**: Medium - requires understanding approval_policy server naming and tool signatures
- **Estimated LOC**: ~50 lines (3 tools × ~13 lines each + client handling + models)

**Agent 6: Agent Info Resource** (~40 min - 1 resource, aggregation logic)
- Implement `resource://agents/{id}/info` (rich agent metadata)
- Aggregate from agent runtime: compositor state, capabilities, mounted servers list
- **Complexity**: Medium - needs to gather data from multiple sources (compositor.sampling_snapshot(), capabilities dict, server list)
- **Estimated LOC**: ~60 lines (1 resource + aggregation logic + comprehensive AgentInfo model)

**Agent 7: Snapshot Resource** (~15 min - 1 resource, pure passthrough)
- Implement `resource://agents/{id}/snapshot` (compositor snapshot)
- Thin wrapper: `infra = await registry.get_infrastructure(agent_id); return await infra.compositor.sampling_snapshot()`
- **Complexity**: Very Low - pure passthrough to existing compositor method
- **Estimated LOC**: ~15 lines (1 resource + 2 lines delegation + model reuse)

**Agent 8: Frontend Migration** (~90 min - update 8+ HTTP endpoints to MCP tools)
- Update `features/agents/api.ts` to call MCP tools instead of HTTP REST
- Replace fetch() calls with MCP client.call_tool() for all 8 agent lifecycle operations
- Update error handling (HTTP status codes → MCP error responses)
- **Complexity**: Medium-High - requires frontend TypeScript understanding, error handling updates
- **Estimated LOC**: ~200 lines changed (replacing ~8 HTTP functions + error handling updates)
- **Dependencies**: All B1-B7 tools must be implemented first

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
- **Type hint migration (REQUIRED)**: Replace `agent_id: str` with `agent_id: AgentID` throughout codebase
  - Pattern: grep for function params `agent_id.*: str` and replace with `AgentID`
  - Update callers to use `AgentID(agent_id_string)` when converting
  - Focus on: mcp_bridge, server, runtime modules
  - Estimated: ~50 occurrences across codebase

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

### Estimated Timeline (Revised with Complexity Analysis)

**Wave A**: ~15 minutes (3 agents, test fixes)
- ResponseUsage: ~5 min (straightforward field additions, 13 sites)
- CallToolResult: ~3 min (add meta={}, 3 sites)
- Event loops: ~7 min (fix asyncio.Runner misuse patterns, 20+ sites - NOT decorator additions since asyncio_mode="auto" already set)

**Wave B**: ~5 hours (12 agents, varies widely by complexity)
- **B1 Backend (Agents 1-7)**: ~3.5 hours total
  - Agents 1-2 (lifecycle + config): ~1 hour (straightforward routing)
  - Agents 3-4 (execution + approvals): ~45 min (mostly aliases + thin routing)
  - Agent 5 (policy tools): ~35 min (get_child_client pattern)
  - Agent 6 (info resource): ~40 min (aggregation logic)
  - Agent 7 (snapshot resource): ~15 min (pure passthrough)
  - **Can run in parallel**: All backend agents independent
- **B2 Tests (Agents 9-12)**: ~30 min total
  - Agent 9 (conftest): ~10 min (fixture updates)
  - Agents 10-11 (test fixes): ~15 min (mechanical updates)
  - Agent 12 (verification): ~5 min (run tests)
  - **Can run in parallel**: Independent test file updates
- **B1 Frontend (Agent 8)**: ~90 min
  - **Must run AFTER B1 backend** (depends on tools existing)
  - Complexity: TypeScript updates, error handling migration

**Wave C**: ~2 hours (8 agents, UI layout + subscriptions)
- Timeline/Policy/Composer: ~1 hour (component extraction/enhancement)
- App.svelte + routing: ~20 min (layout updates)
- MCP subscriptions wiring: ~30 min (resource subscription logic)
- UI server detection + badges: ~10 min (conditional rendering)

**Wave D**: ~1.5 hours (4 agents, backend features)
- Agent state notifications: ~30 min (broadcast_resource_updated wiring)
- Approvals/proposals HTTP: ~30 min (endpoint + MCP integration)
- Loop hooks + DB: ~30 min (hook resources + query tool)

**Wave E**: ~2 hours (28 agents, all scans)
- Scans are fast (grep + pattern matching)
- Most parallelizable wave (28 independent agents)

**Wave F**: ~30 minutes (1 agent, violation analysis)
- Aggregate scan results, prioritize top 5 categories

**Wave G**: ~2 hours (5 agents, cleanup)
- Per-category fixes (~20-30 instances each)
- Complexity varies by violation type

**Wave H**: ~1 hour (6 agents, docs + verify)
- Documentation updates: ~30 min
- Misc cleanups: ~20 min
- Final verification: ~10 min

**Total estimated time**: ~14.5 hours of agent work (with human review between waves)
**Critical path**: Wave A → Wave B (backend) → Wave B (frontend) → Wave C → Wave D → Wave E → Wave F → Wave G → Wave H

**Parallelism opportunities**:
- Wave B: 7 backend agents + 4 test agents run in parallel (11 parallel)
- Wave B: Frontend agent runs sequentially after backend
- Wave C: All 8 UI agents can run in parallel
- Wave E: All 28 scan agents can run in parallel (highest parallelism)

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

### Cross-Agent Routing Architecture

The cross-agent tools in `agents` server are **thin routing wrappers** that delegate to per-agent MCP servers. Two implementation approaches considered:

#### Approach 1: Manual Routing (Current)
Each tool manually resolves agent_id and calls per-agent server:
```python
@server.tool()
async def approve_proposal(agent_id: str, proposal_id: str) -> None:
    infra = await registry.get_infrastructure(AgentID(agent_id))
    client = infra.compositor.get_child_client("approval_policy_admin")
    await client.call_tool("approve_proposal", {"id": proposal_id})
```

**Pros**: Explicit, flexible, easy to add per-agent error handling
**Cons**: Boilerplate for each tool

#### Approach 2: Decorator Pattern (Considered)
Create a decorator that automatically adds agent_id routing:
```python
@route_to_agent_server("approval_policy_admin", "approve_proposal")
async def approve_proposal(agent_id: str, proposal_id: str) -> None:
    pass  # Decorator handles routing
```

**Pros**: Less boilerplate, consistent pattern
**Cons**:
- Magic/implicit behavior
- Harder to customize per-tool error handling
- Requires tool signature inspection/manipulation
- FastMCP may not support wrapping tool functions

**Decision**: Use **Approach 1 (Manual Routing)** for Wave B. The boilerplate is minimal (~3 lines per tool), and explicit routing is clearer for maintenance. Can reconsider decorator pattern if >20 routing tools emerge.

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
