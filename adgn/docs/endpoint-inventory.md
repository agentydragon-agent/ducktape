# Non-MCP Endpoint Inventory for MCPification

**Date**: November 2025
**Status**: Complete enumeration of HTTP and WebSocket endpoints not currently served as MCP resources/tools
**Scope**: Full agent server (`app.py`), channel system (`channels/*.py`), and MCP bridge (`mcp_bridge/server.py`)

---

## Overview

This document catalogs all non-MCP endpoints across the agent infrastructure, identifies which are legitimate non-MCP operations and which should migrate to MCP, and proposes a strategy for progressive MCPification.

### Key Findings

- **31 HTTP REST endpoints** (agent management, runs, proposals, presets)
- **6 WebSocket channel endpoints** (modular UI/state updates)
- **3-4 stub/incomplete endpoints** in MCP bridge mode
- **Categorization**: Most approval/policy endpoints should become MCP tools; agent CRUD and query endpoints can stay HTTP for now; WebSocket channels are intentional non-MCP for UI state streaming

---

## HTTP REST Endpoints (app.py)

### Section A: UI & Static Assets (Keep as-is)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/` | GET | Serve built Svelte app (index.html) | Active | **NO** — static file serving is HTTP-native; MCP has no standard for binary assets |
| `/vite.svg` | GET | Serve Vite logo asset | Active | **NO** — static assets should stay HTTP |

**Rationale**: These are HTTP concerns; MCP is for service semantics, not file serving.

---

### Section B: Capabilities & Diagnostics (Keep as-is)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/capabilities` | GET | Report active components (MCP, approvals, chat, UI) | Active | **MAYBE** — could become `resource://server/capabilities` but HTTP response is simpler for client handshake |

**Rationale**: Used by UI at startup to determine available features. Keep HTTP for fast, non-interactive queries.

---

### Section C: Agent Management (Candidates for MCP tools)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/agents` | GET | List all agents with metadata | Active | **YES** — migrate to MCP resource `resource://agents/list` |
| `/api/agents` | POST | Create agent (preset + optional system) | Active | **YES** — migrate to MCP tool `agents/create_agent(preset, system?)` |
| `/api/agents/{agent_id}` | GET | Get single agent info (live, working, MCP config) | Active | **YES** — migrate to MCP resource `resource://agents/{id}/info` |
| `/api/agents/{agent_id}` | DELETE | Delete agent (stop container, purge DB) | Active | **YES** — migrate to MCP tool `agents/delete_agent(id)` |
| `/api/agents/{agent_id}/boot` | POST | Explicit agent boot (start live container) | Active | **YES** — migrate to MCP tool `agents/boot_agent(id)` |
| `/api/agents/{agent_id}/mcp` | PATCH | Patch agent MCP config (attach/detach) | Active | **YES** — migrate to MCP tool `agents/update_mcp_config(id, config)` |
| `/api/agents/{agent_id}/mcp/attach` | POST | Attach single MCP server | Active | **YES** — migrate to MCP tool `agents/attach_server(id, name, spec)` |
| `/api/agents/{agent_id}/mcp/detach` | POST | Detach single MCP server | Active | **YES** — migrate to MCP tool `agents/detach_server(id, name)` |

**Rationale**: These are all agent lifecycle operations that belong in MCP tools. Leverage the agents MCP server (already partially migrated in `mcp_bridge/servers/agents.py`).

---

### Section D: Agent Execution (Candidates for MCP tools)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/agents/{agent_id}/snapshot` | GET | Get agent snapshot (composed MCP state) | Active | **YES** — migrate to MCP resource `resource://agents/{id}/snapshot` (sampled from compositor) |
| `/api/agents/{agent_id}/status` | GET | Get full agent status (lifecycle, run phase, policy, UI, MCP, container) | Active | **MAYBE** — rich structured status; keep as HTTP for now; could become `resource://agents/{id}/status` later |
| `/api/agents/{agent_id}/prompt` | POST | Send user prompt (start run) | Active | **YES** — migrate to MCP tool `agents/prompt(id, text)` |
| `/api/agents/{agent_id}/abort` | POST | Abort active run | Active | **YES** — migrate to MCP tool `agents/abort_run(id)` |

**Rationale**: Agent execution control (prompt, abort) should be MCP tools. Status/snapshot are query endpoints; status can stay HTTP due to its complexity, snapshot should migrate to MCP.

---

### Section E: Approvals & User Decisions (Candidates for MCP tools)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/agents/{agent_id}/approve` | POST | Approve tool call (continue) | Active | **YES** — migrate to MCP tool `agents/approve_tool_call(id, call_id)` |
| `/api/agents/{agent_id}/deny_continue` | POST | Deny tool call (abort turn) | Active | **YES** — migrate to MCP tool `agents/deny_tool_call(id, call_id)` |
| `/api/agents/{agent_id}/deny_abort` | POST | Deny abort (keep running) | Active | **YES** — migrate to MCP tool `agents/deny_abort(id, call_id)` |

**Rationale**: Approval decisions are domain operations; should be MCP tools for consistency with policy engine. Note: `/ws/approvals` channel broadcasts pending approvals in real-time; both HTTP and WebSocket patterns serve different clients (REST vs. streaming UI).

---

### Section F: Policy Management (Candidates for MCP tools)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/agents/{agent_id}/policy` | POST | Set approval policy (new source code) | Active | **YES** — migrate to MCP tool `agents/set_policy(id, content)` |
| `/api/agents/{agent_id}/proposals` | GET | List policy proposals | Active | **YES** — migrate to MCP resource `resource://agents/{id}/proposals` |
| `/api/agents/{agent_id}/proposals/{proposal_id}` | GET | Get proposal content | Active | **YES** — migrate to MCP resource `resource://approval-policy/proposals/{id}` (via policy server) |
| `/api/agents/{agent_id}/proposals/{proposal_id}/approve` | POST | Approve policy proposal | Active | **YES** — migrate to MCP tool `agents/approve_proposal(id, proposal_id)` |
| `/api/agents/{agent_id}/proposals/{proposal_id}/reject` | POST | Reject policy proposal | Active | **YES** — migrate to MCP tool `agents/reject_proposal(id, proposal_id)` |

**Rationale**: Policy proposals and approvals are governance operations; all should be MCP tools. Related resource URIs already exist in `mcp_bridge/resources.py`.

---

### Section G: Runs & Events (Query endpoints — keep or migrate selectively)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/runs` | GET | List runs (filter by agent, limit) | Active | **MAYBE** — query endpoint; could stay HTTP for pagination simplicity or migrate to resource with continuation tokens |
| `/api/runs/{run_id}` | GET | Get run metadata | Active | **MAYBE** — migrate to `resource://runs/{id}` if needed by external agents; otherwise keep HTTP |
| `/api/runs/{run_id}/events` | GET | Get run event log | Active | **MAYBE** — same as above; event streams can be resources |

**Rationale**: These are read-only query endpoints. HTTP is fine for now; migrating to MCP would require designing resource pagination/filtering (no standard MCP pattern yet). Defer unless external agents need programmatic access.

---

### Section H: Presets (Keep as-is or document in MCP)

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/presets` | GET | List available agent presets | Active | **NO** — preset discovery is a local server concern; not typically shared via MCP |
| `/api/presets/{name}` | GET | Get preset details | Active | **NO** — same reasoning |

**Rationale**: Presets are internal configuration; agents use them when creating agents via the `agents/create_agent(preset)` tool (which will be migrated).

---

## WebSocket Endpoints (channels/*.py)

### Section I: Modular Channel WebSockets (Intentional Non-MCP, Keep as-is)

| Path | Query Param | Channel | Purpose | Status | MCPification? |
|--------|-------------|---------|---------|--------|---------------|
| `/ws/agents` | (none) | agents_hub | Broadcast agent list/status changes to all listeners (no agent_id) | Active | **NO** — general hub; not per-agent; serves UI dashboard |
| `/ws/session` | `?agent_id=<id>` | session | Agent execution state, run status, transcript (user, assistant, tool calls, reasoning) | Active | **NO** — real-time transcript streaming is WebSocket-native; MCP has no standard for continuous message streams |
| `/ws/mcp` | `?agent_id=<id>` | mcp | MCP server state and sampling snapshots (tools, resources, subscriptions) | Active | **NO** — UI state synchronization; distinct from MCP tool invocation |
| `/ws/approvals` | `?agent_id=<id>` | approvals | Pending approvals and decisions for an agent | Active | **NO** — notification channel; approval submission is HTTP/MCP tool; this is state broadcast |
| `/ws/policy` | `?agent_id=<id>` | policy | Active policy content, proposals, and updates | Active | **NO** — policy content broadcast; policy changes driven by `/api/agents/{id}/policy` (→ MCP tool) |
| `/ws/ui` | `?agent_id=<id>` | ui | UI state snapshots and custom messages | Active | **NO** — UI framework concern; not applicable to MCP |

**Rationale**: These channels are **intentional non-MCP patterns** for **streaming UI state** to web clients. They complement HTTP endpoints and MCP tools:

1. **Why not MCP**: MCP resources are static/on-demand reads; MCP has no standard for subscriptions (though `mcp_bridge/todo-mcp-subscriptions.md` explores this). Websockets are the web standard for real-time updates.
2. **Architectural intent**: Modular channels decouple UI subscription from agent execution; separate channel managers allow independent lifetimes.
3. **Envelope convention**: All messages wrapped in `ChannelEnvelope(channel, event_id, event_at, payload)` for reliable ordering and retransmission.

---

## MCP Bridge Endpoints (mcp_bridge/server.py)

### Section J: Bridge Mode HTTP Endpoints

| Path | Method | Purpose | Status | MCPification? |
|------|--------|---------|--------|---------------|
| `/api/agents` | GET | List agents (delegates to MCP resource `resource://agents/list`) | Active | Part of MCP agents server; already MCPfied |
| `/health` | GET | Health check | Active | **NO** — keep as-is; health checks are HTTP convention |
| `/api/capabilities` | GET | Report bridge mode components (no chat/agent_state, has MCP/approvals/policy) | Active | **NO** — keep as-is; diagnostic endpoint |

**Rationale**: Bridge mode uses HTTP for management but routes MCP clients to compositor app via token-authenticated middleware.

---

### Section K: Bridge Mode WebSocket Stubs (Incomplete, TODO)

| Path | Query Param | Purpose | Status | MCPification? |
|--------|-------------|---------|--------|---------------|
| `/ws/policy` | `?agent_id=<id>` | Policy channel (stub) | **TODO** | When implemented, follow modular channel pattern |
| `/ws/approvals` | `?agent_id=<id>` | Approvals channel (stub) | **TODO** | When implemented, follow modular channel pattern |
| `/ws/mcp` | `?agent_id=<id>` | MCP channel (stub) | **TODO** | When implemented, follow modular channel pattern |

**Status**: Returns `{"type": "not_implemented", "message": "...coming soon"}`.

**TODO**: Implement these by reusing channel managers from `adgn.agent.server.channels.*` and wiring to bridge infrastructure.

---

## MCP Bridge: Agents Server (mcp_bridge/servers/agents.py)

This is the **primary MCP interface** for cross-agent control. Already MCPfied; here for reference.

### Resources

| URI | Name | MIME | Purpose |
|-----|------|------|---------|
| `resource://agents/list` | agents.list | application/json | List all agents with capabilities |
| `resource://agents/{agent_id}/state` | agent.state | application/json | Sampling state for local agent (compositor snapshot) |
| `resource://agents/{agent_id}/approvals/pending` | agent.approvals.pending | application/json | Pending approvals for an agent |
| `resource://agents/{agent_id}/approvals/history` | agent.approvals.history | application/json | Approval timeline (completed + pending) |
| `resource://approvals/pending` | approvals.pending.global | application/json | Global mailbox (all pending approvals across agents; multiple content blocks) |
| `resource://agents/{agent_id}/policy/proposals` | agent.policy.proposals | application/json | Policy proposals for an agent |

### Tools

| Name | Purpose |
|------|---------|
| `approve_tool_call(agent_id, call_id)` | Approve a pending tool call |
| `reject_tool_call(agent_id, call_id, reason)` | Reject a tool call |
| `abort_agent(agent_id)` | Abort running local agent |

---

## Categorization & MCPification Strategy

### Category 1: **Keep as-is** (HTTP or WebSocket native, no MCP migration)

- Static file serving (`/`, `/vite.svg`)
- WebSocket channels (`/ws/session`, `/ws/mcp`, `/ws/approvals`, `/ws/policy`, `/ws/ui`)
  - Rationale: Real-time UI state streaming is WebSocket-native; MCP has no standard for continuous subscriptions
- Health checks (`/health`)
- Presets discovery (`/api/presets/*`)
  - Rationale: Internal server config; not shared via MCP

**Count**: 12 endpoints → **Keep**

---

### Category 2: **Migrate to MCP** (HTTP REST → MCP tools/resources)

#### High Priority (Direct user actions, already in bridge/agents server)

- **Agent CRUD & lifecycle** (8 endpoints)
  - `POST /api/agents` → `agents/create_agent(preset, system?)`
  - `GET /api/agents/{agent_id}` → `resource://agents/{id}/info`
  - `DELETE /api/agents/{agent_id}` → `agents/delete_agent(id)`
  - `POST /api/agents/{agent_id}/boot` → `agents/boot_agent(id)`
  - `PATCH /api/agents/{agent_id}/mcp` → `agents/update_mcp_config(id, config)`
  - `POST /api/agents/{agent_id}/mcp/attach` → `agents/attach_server(id, name, spec)`
  - `POST /api/agents/{agent_id}/mcp/detach` → `agents/detach_server(id, name)`
  - `GET /api/agents` → `resource://agents/list` (already exists)

- **Agent execution** (2 endpoints)
  - `POST /api/agents/{agent_id}/prompt` → `agents/prompt(id, text)`
  - `POST /api/agents/{agent_id}/abort` → `agents/abort_run(id)`

- **Approvals** (3 endpoints)
  - `POST /api/agents/{agent_id}/approve` → `agents/approve_tool_call(id, call_id)` (already exists)
  - `POST /api/agents/{agent_id}/deny_continue` → `agents/deny_tool_call(id, call_id)`
  - `POST /api/agents/{agent_id}/deny_abort` → `agents/deny_abort(id, call_id)`

- **Policy** (5 endpoints)
  - `POST /api/agents/{agent_id}/policy` → `agents/set_policy(id, content)`
  - `GET /api/agents/{agent_id}/proposals` → `resource://agents/{id}/proposals`
  - `GET /api/agents/{agent_id}/proposals/{proposal_id}` → `resource://approval-policy/proposals/{id}` (via policy server)
  - `POST /api/agents/{agent_id}/proposals/{proposal_id}/approve` → `agents/approve_proposal(id, proposal_id)`
  - `POST /api/agents/{agent_id}/proposals/{proposal_id}/reject` → `agents/reject_proposal(id, proposal_id)`

#### Medium Priority (Query endpoints, can defer if pagination burden is high)

- **Runs & Events** (3 endpoints)
  - `GET /api/runs` → deferred (may require pagination design)
  - `GET /api/runs/{run_id}` → deferred
  - `GET /api/runs/{run_id}/events` → deferred

**Count**: 21 endpoints → **Migrate to MCP**

---

### Category 3: **Unclear / Deferred** (Needs more context)

- `GET /api/agents/{agent_id}/snapshot` (Snapshot composition)
- `GET /api/agents/{agent_id}/status` (Complex diagnostic structure)
- `GET /api/capabilities` (Handshake helper)

**Action**: Document these and revisit in next planning cycle. For now, keep HTTP.

---

## Migration Roadmap

### Phase 1 (Immediate) — Complete MCP agents server

1. Extend `mcp_bridge/servers/agents.py` with missing tools:
   - `create_agent(preset, system?)`
   - `update_mcp_config(id, config)`, `attach_server(id, name, spec)`, `detach_server(id, name)`
   - `boot_agent(id)`, `delete_agent(id)`
   - `prompt(id, text)`, `abort_run(id)`
   - `deny_tool_call(id, call_id)`, `deny_abort(id, call_id)`
   - `set_policy(id, content)`, `approve_proposal(id, proposal_id)`, `reject_proposal(id, proposal_id)`

2. Add resources (as needed):
   - `resource://agents/{id}/info` (rich agent metadata)
   - `resource://agents/{id}/snapshot` (compositor snapshot, read-only)
   - `resource://agents/{id}/proposals` (list policy proposals)

3. Update **UI** to:
   - Optionally use MCP tools for control (alongside HTTP REST)
   - Or fully migrate UI to MCP client (longer-term)

### Phase 2 (Longer-term) — Deprecate HTTP endpoints

- Keep HTTP endpoints for backward compatibility during transition period
- Add deprecation warnings in server logs
- Encourage clients to migrate to MCP

### Phase 3 (Future) — Remove HTTP, MCP-only

- Sunset HTTP endpoints once MCP tools are stable and widely adopted
- Simplify server code

---

## Open Questions & Recommendations

### Q1: Should agent snapshot/status migrate to MCP?

**Answer**: 
- `snapshot`: **YES**, migrate to `resource://agents/{id}/snapshot` (clean composition boundary)
- `status`: **MAYBE** — rich structure; consider keeping HTTP as-is for now; profile client usage

### Q2: Should runs/events become MCP resources?

**Answer**: **DEFER** — unless external agents need programmatic run history. MCP lacks standard pagination/filtering. Re-evaluate when use case emerges.

### Q3: Should `/ws/session` (transcript) become MCP subscriptions?

**Answer**: **NO** — MCP subscriptions are TBD (`todo-mcp-subscriptions.md`). WebSocket is mature; keep as-is. If MCP subscriptions standardize later, revisit.

### Q4: What about external agents calling the agents server?

**Answer**: They should use MCP tools/resources in `mcp_bridge/servers/agents.py`. HTTP endpoints are for the built-in UI only (short-term).

### Q5: Bridge mode — when do we implement the WebSocket channel stubs?

**Answer**: 
- **Short-term**: Keep stubs; they return "not_implemented"
- **Medium-term**: Implement by reusing channel managers from full agent mode
- **Long-term**: Consider MCP subscriptions as alternative (requires MCP evolution)

---

## Appendix: Endpoint Count Summary

| Category | Count | Action |
|----------|-------|--------|
| Keep as-is | 12 | Static files, WebSockets, diagnostics, presets |
| Migrate to MCP | 21 | Agent CRUD, execution, approvals, policy |
| Defer / Unclear | 3 | Snapshot, status, capabilities |
| Already MCP (bridge agents server) | 9 resources + 3 tools | Reference only |
| Bridge stubs (TODO) | 3 | Implement later |
| **Total non-MCP endpoints** | **36** | — |

---

## References

- `src/adgn/agent/server/app.py` — HTTP REST endpoints
- `src/adgn/agent/server/agents_ws.py` — General agents WebSocket hub
- `src/adgn/agent/server/channels/*.py` — Modular WebSocket channels
- `src/adgn/agent/mcp_bridge/server.py` — MCP bridge server setup
- `src/adgn/agent/mcp_bridge/servers/agents.py` — Agents MCP server (primary MCP interface)
- `docs/vision.md` — Agent design vision and principles
- `docs/todo-mcp-subscriptions.md` — MCP subscriptions roadmap

