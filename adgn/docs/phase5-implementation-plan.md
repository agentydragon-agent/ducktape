# Phase 5 Implementation Plan

## Overview

Two-compositor architecture with token-based routing. Single `/mcp` endpoint serves both users and agents.

## Phase 5a: Core Infrastructure (Backend) ✅

Token routing + dual compositor architecture. Files:
- `mcp_bridge/auth.py` - load_tokens(), TokenRoutingASGI
- `mcp_bridge/registry.py` - InfrastructureRegistry (create/boot/shutdown agents)
- `mcp_bridge/servers/agents.py` - list/presets resources, create/delete/boot tools
- `mcp_bridge/servers/agent_control.py` - send_prompt/abort_run tools
- `server/mcp_routing.py` - MCPRoutingMiddleware for FastAPI

Internal agents get agent_control; external agents don't.

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

## PRs

1. ✅ **Phase 5a**: Core infrastructure (mcp_bridge, token routing, agents/agent_control servers)
2. **Phase 5b**: Frontend migration to MCP
3. **Phase 5c+d**: REST API removal + test coverage
