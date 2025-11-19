# Frontend HTTP/WebSocket Endpoints - Remaining Work

**Last Updated**: 2025-11-19 (Post-Wave D-I)
**Status**: Most endpoints migrated to MCP, 4 endpoints remain

---

## Still In Use (Not Yet Migrated)

### 1. Bootstrap Endpoint (KEEP - Intentional)

#### GET `/api/capabilities`
- **File**: `adgn/src/adgn/agent/web/src/features/agents/api.ts:26`
- **Purpose**: Server capabilities detection before MCP connection established
- **Migration Status**: ✅ **KEEP AS-IS** - Needed for bootstrap before MCP available
- **Notes**: This is intentionally kept as HTTP since MCP connection needs to be established first

---

### 2. WebSocket Channels (TO MIGRATE)

#### WS `/ws/session`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts:128`
- **Purpose**: Agent execution state and transcript
- **Migration Path**: → `resource://agents/{id}/session/state` (MCP resource already exists)
- **Status**: ❌ **NOT YET MIGRATED** - WebSocket still in use
- **Backend Support**: MCP resource exists and functional
- **Frontend Work Needed**:
  - Update `stores_channels.ts` to use MCP subscription instead of WebSocket
  - Replace `handleSessionMessage()` with MCP resource subscription
  - Update `ChannelManager` to remove 'session' channel

#### WS `/ws/policy`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts:130`
- **Purpose**: Policy content updates
- **Migration Path**: → `resource://agents/{id}/policy/state` (MCP resource already exists)
- **Status**: ⚠️ **PARTIALLY MIGRATED** - Mixed usage
  - PolicyEditorPane component: ✅ Uses MCP subscription (`PolicyEditorPane.svelte:67`)
  - stores_channels.ts: ❌ Still uses WebSocket channel
- **Backend Support**: MCP resource exists and functional
- **Frontend Work Needed**:
  - Remove WebSocket 'policy' channel from `stores_channels.ts`
  - Ensure all policy consumers use MCP subscription (like PolicyEditorPane does)

---

## Migration Summary

| Endpoint | Type | Status | MCP Equivalent | Work Needed |
|----------|------|--------|----------------|-------------|
| `/api/capabilities` | HTTP GET | ✅ Keep | N/A (bootstrap) | None - intentional |
| `/ws/session` | WebSocket | ❌ Migrate | `resource://agents/{id}/session/state` | Frontend migration |
| `/ws/policy` | WebSocket | ⚠️ Partial | `resource://agents/{id}/policy/state` | Complete migration in stores |

---

## Completed Migrations (Reference)

The following endpoints have been successfully migrated to MCP:

**MCP Resources in Use**:
- ✅ `resource://agents/list` - Agent list (replaces `/ws/agents`)
- ✅ `resource://agents/{id}/approvals/pending` - Approvals (replaces `/ws/approvals`)
- ✅ `resource://agents/{id}/mcp/state` - MCP servers (replaces `/ws/mcp`)
- ✅ `resource://agents/{id}/ui/state` - UI state (replaces `/ws/ui`)
- ✅ `resource://presets/list` - Presets (replaces `/api/presets`)

**MCP Tools in Use**:
- ✅ `create_agent`, `delete_agent`, `abort_agent`
- ✅ `attach_server`, `detach_server`
- ✅ `approve_tool_call`, `reject_tool_call`, `deny_tool_call`, `deny_abort`
- ✅ `set_policy`, `approve_proposal`, `reject_proposal`
- ✅ `prompt` (send message to agent)

**Deleted Endpoints** (Wave D3):
- All `/api/agents` CRUD endpoints
- All `/api/agents/{id}/approve` approval endpoints
- `/api/agents/{id}/policy` GET/PUT (replaced by MCP)
- `/api/presets` GET (replaced by MCP resource)
- `/ws/agents`, `/ws/approvals`, `/ws/mcp`, `/ws/ui` WebSocket channels

---

## Action Items

### 1. Migrate `/ws/session` to MCP (Priority: HIGH)
**Estimated Time**: 2-3 hours

```typescript
// In stores_channels.ts
// Replace:
manager.on('session', createChannelHandlers('session', handleSessionMessage))

// With:
const uri = `resource://agents/${agentId}/session/state`
await subscriptionManager.subscribe(uri, handleSessionUpdate)
```

**Tasks**:
1. Remove 'session' channel from ChannelManager
2. Create MCP subscription to `resource://agents/{id}/session/state`
3. Update `handleSessionMessage` to `handleSessionUpdate` (process MCP resource data)
4. Test transcript display, live updates, run status

### 2. Complete `/ws/policy` Migration (Priority: MEDIUM)
**Estimated Time**: 1 hour

**Tasks**:
1. Remove 'policy' channel from ChannelManager in `stores_channels.ts`
2. Update `approvalPolicy` store to use MCP subscription (like PolicyEditorPane)
3. Verify proposal notifications work via MCP
4. Test policy editor, proposals panel

---

## Testing Checklist

After completing migrations:

- [ ] `/ws/session` removed: Transcript updates work via MCP subscription
- [ ] `/ws/policy` removed: Policy editor and proposals work via MCP
- [ ] No WebSocket connections except MCP's `/mcp` endpoint
- [ ] All frontend components using MCP subscriptions for live updates
- [ ] E2E tests pass (test_mcp_ui.py, test_mcp_concurrent.py)

---

## Notes

- **Bootstrap Endpoint**: `/api/capabilities` is intentionally kept as HTTP since it's needed before MCP connection is established
- **MCP Infrastructure**: All MCP resources are fully implemented and functional on the backend
- **WebSocket Cleanup**: Once session/policy channels are migrated, only the MCP StreamableHTTP endpoint (`/mcp`) should remain
- **Token-Based Routing**: The `/mcp` endpoint routes connections based on Bearer token role (HUMAN vs AGENT)
