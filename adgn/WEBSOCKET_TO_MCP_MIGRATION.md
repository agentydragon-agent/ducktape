# WebSocket to MCP Migration

Migration from WebSocket-based communication to MCP (Model Context Protocol) for the agent web UI.

**Status**: ✅ COMPLETED

## Architecture

**Architecture**: Frontend ↔ MCP HTTP (`/mcp`) with Bearer token auth ↔ Two-Level Compositor ↔ FastMCP Servers

### Two-Level Compositor Architecture

**Level 1: Global Compositor** (user-facing)
- Single `/mcp` endpoint with token-based routing
- Mounts `agents` server for global operations (list/create/delete agents)
- Mounts per-agent sub-compositors dynamically

**Level 2: Per-Agent Sub-Compositors**
- Each agent gets its own compositor with agent-specific servers
- Internal agents get `agent_control` server (send_prompt, abort_run)
- External agents (Claude Code) don't get agent_control

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `TokenRoutingASGI` | `mcp_bridge/auth.py` | Routes tokens to user/agent compositors |
| `InfrastructureRegistry` | `mcp_bridge/registry.py` | Agent lifecycle management |
| `agents` server | `mcp_bridge/servers/agents.py` | List presets, create/delete/boot agents |
| `agent_control` server | `mcp_bridge/servers/agent_control.py` | send_prompt, abort_run tools |
| `MCPRoutingMiddleware` | `server/mcp_routing.py` | FastAPI middleware for MCP routing |

## Completed Phases

### Phase 1-4: Core Migration ✅
- Deleted WebSocket files and code
- Wired approvals server to compositor
- Migrated frontend to MCP client
- Migrated stores to MCP tools/resources

### Phase 5: Two-Compositor Architecture ✅
- Token-based routing (`mcp_bridge/auth.py`)
- Infrastructure registry for agent lifecycle
- Agents management MCP server
- Agent control MCP server
- Frontend migration to MCP (deleted `api.ts`)
- REST API removal (only `/`, `/mcp`, static assets remain)
- Test coverage in `tests/mcp_bridge/test_integration.py`

### Phase 6: Dead Code Cleanup ✅
- Removed dead `send_payload` calls
- Marked/removed dead protocol event types
- Documented dead code paths

## Server Architecture

### Per-Agent Servers (mounted on agent compositor)
1. **resources** - Aggregates resources from all servers
2. **compositor_meta** - Compositor state/metadata
3. **compositor_admin** - Mount lifecycle (attach/detach)
4. **chat.human/assistant** - Chat message stores
5. **ui** - UI message display
6. **loop** - Loop control
7. **approval_policy** - Policy evaluation & resources
8. **policy_proposer** - Create/withdraw proposals
9. **runtime** - Container exec
10. **approvals** - User approval actions

### Global Servers (mounted on global compositor)
1. **agents** - List presets, create/delete/boot agents
2. Per-agent sub-compositors (mounted dynamically)

## Frontend Files

- `mcp/client.ts` - StreamableHTTPClientTransport + bearer token auth
- `mcp/manager.ts` - Global MCP client for agent-agnostic ops
- `agents/stores.ts` - MCP-based listPresets, createAgent, deleteAgent
- `chat/stores.ts` - MCP-based approval actions, server attach/detach
