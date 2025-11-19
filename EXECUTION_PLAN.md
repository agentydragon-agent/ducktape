# Execution Plan: Remaining Work

## Status Summary

**✅ COMPLETED**:
- Wave A: Pre-requisite test fixes (3 agents - ResponseUsage, CallToolResult, Event loops)
- Wave B: Infrastructure migration (12 agents - HTTP→MCP backend + frontend + WebSocket tests)

**🚧 REMAINING**:
- Wave C: UI Layout Implementation
- Wave D: Backend Feature Complete
- Wave E: Code Quality Scans
- Wave F: Violation Analysis
- Wave G: Parallel Cleanup
- Wave H: Documentation & Verification

## Execution Strategy

**Parallel execution within waves**: Launch all agents in a wave simultaneously using a single message with multiple Task tool calls.

**Serial between waves**: Each wave depends on the previous wave completing.

**Agent configuration**:
- `model="haiku"` for straightforward tasks (scans, cleanups, simple routing)
- `model="sonnet"` for complex tasks (migrations, implementations, analysis)
- `subagent_type="general-purpose"` for all agents

## Wave C: UI Layout Implementation (~2 hours, 8 parallel agents)

**Dependencies**: Wave B complete (MCP tools available)

- **Agent 1**: AgentTimeline Enhancement
  - Rename `ApprovalTimeline.svelte` → `AgentTimeline.svelte`
  - Merge `UiDisplayItem[]` from `uiState` store
  - Show approvals, tool calls, UI messages in unified timeline

- **Agent 2**: PolicyEditorPane Extraction
  - Extract from `ApprovalsPanel.svelte`
  - Policy view/edit + proposals UI
  - Component: `PolicyEditorPane.svelte`

- **Agent 3**: MessageComposer Completion
  - Complete `MessageComposer.svelte`
  - Send messages, abort agent
  - Only shown for local agents with UI server

- **Agent 4**: App.svelte Layout
  - CSS grid: `timeline | policy` + conditional composer
  - Side-by-side layout per mockups

- **Agent 5**: MCP Subscriptions Wiring
  - Wire `resource://agents/{id}/approvals/history`
  - Wire `resource://approval-policy/policy.py`
  - Update components to use subscriptions

- **Agent 6**: UI Server Detection
  - Check `$agentStatus.ui?.ready`
  - Conditional composer rendering
  - Show UI messages in timeline

- **Agent 7**: Agent Mode Badge
  - Add [LOCAL] or [BRIDGE] badge
  - Indicates agent loop presence
  - UI server shown implicitly via composer/timeline

- **Agent 8**: Routing Updates
  - Global approvals view
  - Agent selection routing
  - Navigation between views

## Wave D: Backend Feature Complete (~1 hour, 3 parallel agents)

**Dependencies**: Wave C complete

- **Agent 1**: Agent State Notifications
  - Wire `resource://agents/{id}/state` to emit `resource_updated` notifications
  - MCP subscriptions already work (`NotifyingFastMCP.broadcast_resource_updated()` implemented)
  - Focus: connect compositor/session events to broadcast calls
  - Pattern: compositor events (user prompt, assistant message, tool call, approval decision) → `server.broadcast_resource_updated(resources.agent_state(agent_id))`
  - Verify: frontend subscriptions receive live updates

- **Agent 2**: Token-Based Capability Middleware
  - Implement `TokenCapabilityMiddleware` for agents MCP server
  - Define `TokenRole` enum (HUMAN, AGENT) - only two roles, no separate admin
  - Extract role from JWT token (returns TokenRole enum)
  - Define tool access lists:
    - `AGENT_ONLY_TOOLS = ["withdraw_proposal"]` (agents can withdraw own proposals, humans cannot)
  - Implement middleware methods:
    - `on_call_tool()` - block unauthorized tool calls (raise `McpError(FORBIDDEN)`)
    - `on_list_tools()` - filter tool list based on role
    - `on_list_resources()` - filter resource list based on role (currently no filtering)
    - `on_read_resource()` - control resource access by role (currently no restrictions)
    - `on_notification()` - filter resource update notifications by role (pass through for now)
  - Pattern follows existing `PolicyGatewayMiddleware` in codebase
  - Test: human cannot call `withdraw_proposal`, agent can
  - **Note**: Single MCP server on same port, different capabilities per token role

- **Agent 3**: DELETE Legacy HTTP/WebSocket Endpoints
  - Verify frontend only uses MCP (no HTTP calls to `/api/agents/*`)
  - Delete HTTP agent management endpoints (keep static/health/presets only)
  - Delete WebSocket channel infrastructure (`/ws/*` endpoints)
  - Delete channel bundle code (`_channel_bundle`, `channel.bundle`)
  - **VERIFY**: ZERO WebSocket endpoints remain (only MCP StreamableHTTP)
  - **NOTE**: Proposals already work via policy server MCP resources

## Wave E: Code Quality Scans (~2 hours, 28 parallel agents)

**Dependencies**: Wave D complete (all code in place)

Run each scan prompt from `prompts/scans/` in parallel:

- Agent 1: api-model-design.md
- Agent 2: asyncio-antipatterns.md
- Agent 3: denormalized-computed-fields.md
- Agent 4: duplicated-test-code.md
- Agent 5: error-swallowing.md
- Agent 6: fastmcp-documentation-patterns.md
- Agent 7: functional-over-imperative.md
- Agent 8: identifier-naming.md
- Agent 9: library-type-misuse.md
- Agent 10: manual-serde-needs-pydantic.md
- Agent 11: methods-vs-freestanding.md
- Agent 12: missing-dataclass-pydantic.md
- Agent 13: mypy-appeasing-code.md
- Agent 14: overly-loose-typing.md
- Agent 15: pydantic-antipatterns.md
- Agent 16: pygit2-patterns.md
- Agent 17: pytest-tmp-paths.md
- Agent 18: stringly-typed.md
- Agent 19: suspicious-defaults.md
- Agent 20: suspicious-nullability.md
- Agent 21: test-assertions.md
- Agent 22: timestamp-naming.md
- Agent 23: trivial-forwarder-methods.md
- Agent 24: trivial-forwarders.md
- Agent 25: type-ignore-suppressions.md
- Agent 26: unnecessary-verbosity.md
- Agent 27: useless-comments-and-docs.md
- Agent 28: useless-documentation.md
- Agent 29: useless-test-classes.md
- Agent 30: walrus-get-pattern.md

**Note**: Some scans may not apply to codebase (e.g., pygit2-patterns if no pygit2 usage)

## Wave F: Violation Analysis (~30 min, 1 agent)

**Dependencies**: Wave E complete (all scan results available)

- **Agent 1**: Analyze all scan results
  - Aggregate findings by category
  - Prioritize violations by severity/frequency
  - Create cleanup plan for Wave G
  - Identify top 5 categories for parallel cleanup

## Wave G: Parallel Cleanup (~2 hours, 5 parallel agents)

**Dependencies**: Wave F complete (analysis done)

Based on Wave F analysis, create 5 parallel cleanup agents targeting:

- **Agent 1**: Top violation category 1 (e.g., error-swallowing)
  - Fix ~20-30 instances

- **Agent 2**: Top violation category 2 (e.g., unnecessary-verbosity)
  - Fix ~20-30 instances

- **Agent 3**: Top violation category 3 (e.g., type-ignore-suppressions)
  - Fix ~20-30 instances

- **Agent 4**: Top violation category 4 (e.g., duplicated-test-code)
  - Fix ~20-30 instances

- **Agent 5**: Top violation category 5 (e.g., suspicious-nullability)
  - Fix ~20-30 instances

## Wave H: Documentation & Verification (~1 hour, 6 parallel agents)

**Dependencies**: Wave G complete (cleanup done)

- **Agent 1**: MCP Runtime Documentation
  - Update docs after loop hooks + DB server land
  - Document new MCP resources and tools

- **Agent 2**: Chat Inbox Architecture Docs
  - Document chat inbox architecture
  - MCP-native chat delivery patterns

- **Agent 3**: Sandboxer/MCP Cross-References
  - Cross-reference seatbelt TODO in sandboxer/MCP docs
  - Link related security considerations

- **Agent 4**: Plan.md Compression
  - Compress completed sections (reference code, not specs)
  - Keep plan.md focused on remaining/future work

- **Agent 5**: Misc Cleanups
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

- **Agent 6**: Final Verification
  - Run: `uv run ruff check . --fix`
  - Run: `uv run python -m mypy adgn`
  - Run: `pytest -q adgn/tests/agent`
  - Verify all tests pass
  - Verify no type errors
  - Verify no linting errors

## Success Criteria

### Wave C Success
- UI layout matches mockups
- AgentTimeline shows unified events
- PolicyEditorPane functional
- MessageComposer works for local+UI agents

### Wave D Success
- Agent state notifications emit `resource_updated` on compositor events
- Token-based capability middleware blocks unauthorized tool calls (human cannot withdraw_proposal)
- Middleware filters notifications by role
- Legacy HTTP agent endpoints DELETED (only static/health/presets remain)
- WebSocket channel infrastructure DELETED (`/ws/*` endpoints removed)
- ZERO WebSocket endpoints remain (only MCP StreamableHTTP)

### Wave E Success
- 28-30 scan reports generated
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

## Estimated Timeline

**Wave C**: ~2 hours (8 agents, UI layout + subscriptions)
**Wave D**: ~1.5 hours (4 agents, backend features)
**Wave E**: ~2 hours (28-30 agents, all scans)
**Wave F**: ~30 minutes (1 agent, violation analysis)
**Wave G**: ~2 hours (5 agents, cleanup)
**Wave H**: ~1 hour (6 agents, docs + verify)

**Total remaining time**: ~9 hours of agent work (with human review between waves)

## Architecture Notes

### Token-Based Capability Middleware (NEW Pattern - Wave D)

**Key Insight**: MCP subscriptions ALREADY WORK (`NotifyingFastMCP.broadcast_resource_updated()` implemented in Wave B).

Instead of running separate MCP servers for different audiences (e.g., `agents` server and `human` server), use **one MCP server that presents different tools/resources based on the presented token**.

FastMCP's middleware pattern (like existing `PolicyGatewayMiddleware`) makes this easy:

```python
from enum import StrEnum

class TokenRole(StrEnum):
    """MCP server access roles derived from JWT token."""
    HUMAN = "human"  # Human UI and admin operations
    AGENT = "agent"  # Agent self-management

class TokenCapabilityMiddleware(Middleware):
    """Filter MCP tools/resources by token role (human vs agent)."""

    # Define access control lists
    AGENT_ONLY_TOOLS = {"withdraw_proposal"}  # Agents can withdraw own proposals

    async def call_tool(self, name: str, args: dict, ctx: RequestContext, call_next):
        role = extract_role_from_token(ctx.auth_token)  # Returns TokenRole enum

        # Block agent-only tools from human UI
        if role == TokenRole.HUMAN and name in self.AGENT_ONLY_TOOLS:
            raise McpError(FORBIDDEN, f"Tool {name} only available to agents")

        return await call_next(name, args)

    async def list_tools(self, ctx: RequestContext, call_next):
        """Filter tool list based on role."""
        all_tools = await call_next()
        role = extract_role_from_token(ctx.auth_token)

        if role == TokenRole.HUMAN:
            # Filter out agent-only tools from human UI
            return [t for t in all_tools if t.name not in self.AGENT_ONLY_TOOLS]
        else:
            # Agents see all tools
            return all_tools

    async def list_resources(self, ctx: RequestContext, call_next):
        """Filter resource list based on role (currently no filtering needed)."""
        return await call_next()

    async def on_read_resource(
        self, context: MiddlewareContext[ReadResourceRequestParams], call_next
    ):
        """Control resource access by role (currently no restrictions)."""
        return await call_next(context)

    async def on_notification(
        self, context: MiddlewareContext[Notification[Any, Any]], call_next
    ):
        """Filter resource update notifications by role.

        This intercepts notifications/resources/updated messages and can filter
        which clients receive them based on token role.
        """
        # For now, pass through all notifications (no filtering yet)
        # Future: filter by checking context.message.method == "notifications/resources/updated"
        # and examining the URI to determine if the resource should be visible to this role
        return await call_next(context)
```

**Benefits**:
- Single MCP server, single port
- Simpler deployment (no multiple server processes)
- Easier to reason about (one codebase, token determines view)
- Token becomes the capability selector
- Follows existing `PolicyGatewayMiddleware` pattern in codebase

**MCP Subscriptions Status**:
- ✅ `NotifyingFastMCP.broadcast_resource_updated()` implemented and tested (Wave B)
- ✅ Frontend subscription client working (107 tests passing)
- Wave D Agent 1: Wire compositor events → broadcast calls
- No new infrastructure needed - just connect the dots

### Cross-Agent Routing Architecture

Cross-agent tools are **thin routing wrappers** over existing single-agent MCP servers:

```python
@server.tool()
async def approve_proposal(agent_id: AgentID, proposal_id: str) -> SimpleOk:
    infra = await registry.get_infrastructure(agent_id)
    client = infra.compositor.get_child_client("approval_policy_admin")
    await client.call_tool("approve_proposal", {"id": proposal_id})
    return SimpleOk(ok=True)
```

**DO**:
- Route to existing single-agent servers via `compositor.get_child_client()`
- Delegate to Python APIs (e.g., `compositor.mount_server()`)
- Add agent_id parameter to tools
- Provide error handling for agent not found

**DON'T**:
- Reimplement business logic
- Duplicate state management
- Bypass single-agent servers

## Deferred to Future

- WebSocket → MCP subscription migration (Phase 2)
  - Requires MCP subscription infrastructure fully reliable
  - Definition of Done documented in plan.md
- Svelte component test execution
  - Blocked by Svelte 6 + vitest incompatibility
  - 45 tests written, waiting for upstream fix
- E2E tests execution
  - Requires Docker daemon
  - 3 tests written, marked `@pytest.mark.requires_docker`

## Out of Scope

- Runs & Events endpoints (`/api/runs/*`)
  - Deferred until pagination/filtering design
- Agent status resource (`resource://agents/{id}/status`)
  - Deferred due to complex structure
- Server capabilities resource
  - Deferred as handshake helper
