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
  - Collapse approval and tool calls into ONE widget per call ID (show inputs AND outputs together)
  - Merge `UiDisplayItem[]` from `uiState` store (UserMessage, AssistantMarkdown, Tool, EndTurn)
  - Subscribe to agent-scoped approval policy: `resource://agents/{id}/approval-policy/policy.py` (NOT global)
  - Wire agent to ensure scoped policy resource is exposed properly
  - UI server messages: subscribe to notifications FROM the UI server (not just read resource)

- **Agent 2**: PolicyEditorPane Extraction
  - Extract from `ApprovalsPanel.svelte`
  - Policy view/edit + proposals UI
  - Component: `PolicyEditorPane.svelte`
  - Agent-scoped policy resource integration

- **Agent 3**: MessageComposer Component
  - Complete `MessageComposer.svelte` for sending messages to agent
  - Conditional rendering based on UI server presence (check `$agentStatus.ui?.ready`)
  - Separate sub-component for message sending

- **Agent 4**: App.svelte Layout
  - CSS grid: `timeline | policy` + conditional components
  - MessageComposer (conditional on UI server)
  - AbortButton (conditional on loop server)
  - Side-by-side layout per mockups

- **Agent 5**: MCP Subscriptions Wiring
  - Subscribe to `resource://agents/{id}/approvals/history`
  - Subscribe to `resource://agents/{id}/approval-policy/policy.py` (agent-scoped)
  - Subscribe to UI server notifications (for message rendering)
  - Update components to use subscriptions

- **Agent 6**: UI Server Detection
  - Check `$agentStatus.ui?.ready` for MessageComposer rendering
  - Show UI messages in timeline from UI server notifications

- **Agent 7**: Agent Controls Component
  - Add agent mode badge: [LOCAL] or [BRIDGE] (indicates agent loop presence)
  - Add ABORT button as separate sub-component
  - Abort button conditional on LOOP server presence (NOT UI server)
  - Abort button triggers tool to abort the loop
  - **Note**: UI server and loop server are SEPARATE conditionals

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

- **Agent 2**: Token-Based Connection Routing
  - Implement token-based routing at `/mcp` endpoint (not `/mcp/agents`)
  - Define `TokenRole` enum (HUMAN, AGENT) - only two roles, no separate admin
  - Extract Bearer token from Authorization header and look up in token table
  - Token table lookup returns `{role: "human" | "agent", agent_id?: str}`
  - Route based on role using `StreamableHTTPSessionManager`:
    - **AGENT** role (with agent_id) → Route to agent's compositor MCP server
    - **HUMAN** role → Route to agents management MCP server
  - Each connection gets its own session manager for the appropriate backend
  - Client sees backend directly (no prefixes) - transparent proxy
  - Pattern: Custom ASGI app → token lookup → get/create session manager → delegate to `manager.handle_request()`
  - Test: agent token connects to compositor, human token connects to management server
  - **Note**: Single HTTP endpoint, per-connection routing (not per-request middleware)

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
- Token-based routing forwards connections to correct backend (compositor or management server)
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

### Token-Based Connection Routing (NEW Pattern - Wave D)

**Key Insight**: Use per-connection routing with `StreamableHTTPSessionManager` to route connections to different backend MCP servers based on Bearer token lookup.

Instead of running separate HTTP endpoints, use **one HTTP endpoint (`/mcp`) that routes each connection to the appropriate backend MCP server based on the Bearer token**.

The implementation uses `StreamableHTTPSessionManager` (from MCP SDK) to manage sessions with different backend servers:

```python
from enum import StrEnum
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Scope, Receive, Send

class TokenRole(StrEnum):
    """MCP connection routing roles from token table lookup."""
    HUMAN = "human"  # Routes to agents management server
    AGENT = "agent"  # Routes to agent's compositor

class MCPRoutingHandler:
    """Custom ASGI app that routes MCP connections based on Bearer token."""

    def __init__(self, token_table: dict[str, dict], registry: AgentRegistry):
        self.token_table = token_table
        self.registry = registry
        # Cache session managers per backend
        self.session_managers: dict[str, StreamableHTTPSessionManager] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Extract Bearer token from Authorization header
        token = extract_bearer_token(scope["headers"])

        # Look up token in table
        token_info = self.token_table.get(token)  # {role: "human" | "agent", agent_id?: str}

        if not token_info:
            # Return 401 Unauthorized
            return

        role = TokenRole(token_info["role"])

        # Get or create session manager for the appropriate backend
        if role == TokenRole.AGENT:
            agent_id = token_info["agent_id"]
            backend_key = f"agent:{agent_id}"
            if backend_key not in self.session_managers:
                # Get agent's compositor MCP server
                infra = await self.registry.get_infrastructure(agent_id)
                compositor_server = infra.compositor._mcp_server
                self.session_managers[backend_key] = StreamableHTTPSessionManager(
                    app=compositor_server,
                    json_response=False
                )
        elif role == TokenRole.HUMAN:
            backend_key = "human"
            if backend_key not in self.session_managers:
                # Get agents management MCP server
                management_server = get_agents_management_server()
                self.session_managers[backend_key] = StreamableHTTPSessionManager(
                    app=management_server,
                    json_response=False
                )

        # Route this connection to the appropriate session manager
        manager = self.session_managers[backend_key]
        await manager.handle_request(scope, receive, send)
```

**Benefits**:
- Single HTTP endpoint, single port (`/mcp`)
- ALL MCP protocol messages forwarded to appropriate backend
- No prefixes - client sees backend tools/resources directly
- Per-connection routing (not per-request)
- Each connection transparently proxies to correct backend
- No filtering logic needed - backend serves correct capabilities

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
