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

## Phase 5b: Frontend Migration ✅

Frontend migrated from REST API to MCP. Files:
- `mcp/client.ts` - StreamableHTTPClientTransport + bearer token auth
- `mcp/manager.ts` - global MCP client for agent-agnostic ops
- `agents/stores.ts` - MCP-based listPresets, createAgent, deleteAgent, getProposal
- `chat/stores.ts` - MCP-based attachMcpServer, detachMcpServer
- `api.ts` - deleted (all REST calls replaced)

Components updated: AgentsSidebar, App, ServersPanel, ProposalCard, RightSidebar.

---

## Phase 5c: REST API Removal ✅

**Goal**: Clean removal of REST endpoints.

- [x] Remove all `/api/*` routes from `app.py`
- [x] Keep only: `/`, `/vite.svg`, `/static/*`, `/assets/*`, `/mcp`
- [x] Update CLI to print authenticated URL: `http://host:port?token=...`
- [x] Update README documentation

---

## Phase 5d: Test Coverage

- [x] Unit tests for `TokenRoutingASGI`
- [x] Unit tests for `InfrastructureRegistry`
- [x] Unit tests for `agents` server
- [ ] Integration tests for full user flow (future)
- [ ] Integration tests for external agent flow (future)

---

## PRs

1. ✅ **Phase 5a**: Core infrastructure (mcp_bridge, token routing, agents/agent_control servers)
2. ✅ **Phase 5b**: Frontend migration to MCP
3. **Phase 5c+d**: REST API removal + test coverage
