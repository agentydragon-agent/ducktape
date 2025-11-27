# Phase 5 Implementation Plan

## Overview

Two-compositor architecture with token-based routing. Single `/mcp` endpoint serves both users and agents.

## Phase 5a: Core Infrastructure (Backend) ✅

**Goal**: Token routing + dual compositor architecture working, no frontend changes yet.

### 5a.1: Types and Utilities ✅
- [x] Create `AgentID` type with Pydantic validation in `agent/types.py`
- [x] Create `mcp_bridge/` module structure
- [x] Implement `load_tokens()` in `mcp_bridge/auth.py`
- [x] Implement `TokenRoutingASGI` in `mcp_bridge/auth.py`

### 5a.2: Infrastructure Registry ✅
- [x] Create `InfrastructureRegistry` class in `mcp_bridge/registry.py`
  - `boot_agent(id)` - boot existing agent from DB
  - `create_agent(preset)` - create new + boot
  - `create_external_agent(id)` - for startup
  - `shutdown_agent(id)`
  - `get_agent(id)` - lookup

### 5a.3: Agents Management Server ✅
- [x] Create `mcp_bridge/servers/agents.py`
  - `list` resource (all agents with state)
  - `presets` resource
  - `create_agent` tool
  - `delete_agent` tool
  - `boot_agent` tool
- [x] Wire up resource notifications on agent state changes

### 5a.4: Dual Compositor in AgentContainer ✅
- [x] Agent compositor (existing + policy gateway)
- [x] Add `external: bool` flag to control `agent_control` mounting
- [x] Mount `agent_control` for internal agents only

Note: Full dual compositor (separate user/agent views) deferred to future iteration.
Current approach mounts agent_control conditionally on single compositor.

### 5a.5: Agent Control Server ✅
- [x] Create `mcp_bridge/servers/agent_control.py`
  - `send_prompt` tool
  - `abort_run` tool
- [x] Wire to container methods

### 5a.6: Update app.py ✅
- [x] New lifespan with token loading + external agent startup
- [x] Integrate InfrastructureRegistry and global compositor
- [x] Create MCPRoutingMiddleware for token-based routing
- [x] Keep REST API endpoints (frontend still uses them)

### 5a.7: Integration Test ✅
- [x] Basic tests for load_tokens
- [x] Basic tests for agents server creation
- [x] Basic tests for agent_control server creation

---

## Phase 5b: Frontend Migration

**Goal**: Frontend talks to MCP instead of REST API.

### 5b.1: MCP Client Update
- [ ] Switch from SSE to Streamable HTTP transport
- [ ] Add bearer token support (from URL query param)
- [ ] Update resource URIs to prefixed format

### 5b.2: Migrate API Calls
- [ ] Replace `api.listAgents()` → `mcp.readResource('agents://agents/list')`
- [ ] Replace `api.createAgent()` → `mcp.callTool('agents_create_agent')`
- [ ] Replace `api.sendPrompt()` → `mcp.callTool('agent_{id}_agent_control_send_prompt')`
- [ ] Replace all approval calls → `agent_{id}_admin_*` tools
- [ ] Subscribe to resource updates for real-time UI

### 5b.3: Delete api.ts
- [ ] Remove `api.ts` entirely
- [ ] Update all imports

---

## Phase 5c: REST API Removal

**Goal**: Clean removal of REST endpoints.

- [ ] Remove all `/api/*` routes from `app.py`
- [ ] Keep only: `/`, `/vite.svg`, `/static/*`, `/mcp`
- [ ] Update CLI to print authenticated URL: `http://host:port?token=...`

---

## Phase 5d: Test Coverage

- [ ] Unit tests for `TokenRoutingASGI`
- [ ] Unit tests for `InfrastructureRegistry`
- [ ] Unit tests for `agents` server
- [ ] Integration tests for full user flow
- [ ] Integration tests for external agent flow

---

## Suggested Order of PRs

1. **PR 1**: Types + mcp_bridge module structure + TokenRoutingASGI + load_tokens
2. **PR 2**: InfrastructureRegistry + agents server
3. **PR 3**: Dual compositor in AgentContainer + agent_control server
4. **PR 4**: app.py integration (REST API still works)
5. **PR 5**: Frontend migration to MCP
6. **PR 6**: REST API removal + CLI authenticated URL
