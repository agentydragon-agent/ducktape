# WebSocket Channels Migration Guide

## Overview

The frontend WebSocket connection has been split from a monolithic `/ws` endpoint into **5 modular channels**, each mapping to a specific backend component.

## Old Architecture (Monolithic)

```typescript
// Single WebSocket connection
connectWS(agentId) -> /ws?agent_id=xyz

// All messages on one channel
{
  "session_id": "...",
  "event_id": 123,
  "payload": {
    "type": "snapshot",  // Bundles everything together
    "details": {
      "run_state": {...},
      "sampling": {...},
      "approval_policy": {...}
    }
  }
}
```

## New Architecture (Modular Channels)

```typescript
// Multiple channel connections
ChannelManager(agentId)
  .on('session', ...)    -> /ws/session?agent_id=xyz
  .on('mcp', ...)        -> /ws/mcp?agent_id=xyz
  .on('approvals', ...)  -> /ws/approvals?agent_id=xyz
  .on('policy', ...)     -> /ws/policy?agent_id=xyz
  .on('ui', ...)         -> /ws/ui?agent_id=xyz
  .connect()

// Each channel has specific messages
// /ws/mcp:
{
  "channel": "mcp",
  "event_id": 42,
  "payload": {
    "type": "mcp_snapshot",
    "sampling": {...}  // Only MCP state
  }
}
```

## Channel Mapping

| Channel | Component | Availability | Messages |
|---------|-----------|-------------|----------|
| **session** | `LocalAgentRuntime.session` | Local agents only | `session_snapshot`, `run_status`, transcript items |
| **mcp** | `RunningInfrastructure.compositor` | Always | `mcp_snapshot`, `mcp_server_attached/detached` |
| **approvals** | `RunningInfrastructure.approval_hub` | Always | `approvals_snapshot`, `approval_pending/decision` |
| **policy** | `RunningInfrastructure.approval_engine` | Always | `policy_snapshot`, `policy_updated`, proposals |
| **ui** | `AgentRuntime._ui_manager` | Optional | `ui_state_snapshot/updated`, UI messages |

## Migration Steps

### 1. Replace imports

```typescript
// Old
import { connectAgentWs, disconnectAgentWs } from './features/chat/stores'

// New
import {
  connectAgentChannels,
  disconnectAgentChannels
} from './features/chat/stores_channels'
```

### 2. Update connection calls

```typescript
// Old
connectAgentWs(agentId)
disconnectAgentWs()

// New
connectAgentChannels(agentId)
disconnectAgentChannels()
```

### 3. Use channel-aware state

```typescript
// Old - single connection state
import { wsConnected } from './features/chat/stores'

// New - per-channel state
import { channelsConnected } from './features/chat/stores_channels'

// Check if specific channel is connected
$channelsConnected.has('mcp')  // true/false
$channelsConnected.has('session')  // true/false (only for local agents)
```

## Benefits

1. **Explicit Modularity**: Each channel maps to one component
2. **Selective Subscription**: Connect only to needed channels
3. **Remote Agent Support**: External agents use `mcp/approvals/policy` only
4. **Clear Availability**: Missing component = channel not available
5. **Better Errors**: Know which component failed
6. **Independent Evolution**: Channels can change separately

## Backward Compatibility

The old monolithic `/ws` endpoint still exists and will continue to work during the migration period. Both can coexist:

- Old code uses `/ws` (bundled messages)
- New code uses `/ws/mcp`, `/ws/approvals`, etc. (modular)

## Example: Remote Agent

For a remote agent (external LLM provider connected via HTTP MCP bridge):

```typescript
// Remote agent - no session/ui channels
connectAgentChannels(remoteAgentId)
// Opens: /ws/mcp, /ws/approvals, /ws/policy
// Skips: /ws/session (not available), /ws/ui (not available)

// UI shows only policy + approvals + MCP state
// No run status, no transcript (agent runs externally)
```

## Testing

1. Open browser DevTools -> Network -> WS
2. Should see 4-5 WebSocket connections (depending on components)
3. Each shows separate message stream
4. Check console for `[WS:mcp]`, `[WS:approvals]`, etc. logs

## Rollback

If issues arise, revert imports back to `stores.ts` (old monolithic approach). The backend supports both simultaneously.
