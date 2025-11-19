# GlobalApprovalsList Component

## Overview

The `GlobalApprovalsList.svelte` component displays all pending approvals across all agents in a unified global mailbox view. It demonstrates MCP (Model Context Protocol) integration for fetching resources and calling tools.

## Implementation Status

### ✅ Implemented Features

1. **MCP Resource Integration**
   - Fetches `resource://approvals/pending` via MCP client
   - Parses multiple `TextResourceContents` blocks correctly
   - Extracts `{ agent_id, call_id, tool, args, timestamp }` from each block

2. **Display Features**
   - Groups approvals by `agent_id`
   - Shows tool name and call_id
   - Displays timestamp in user's locale
   - Expandable/collapsible arguments view using `JsonDisclosure`
   - Compact card-based layout

3. **Approval Actions**
   - **Approve button** → Calls `approve_tool_call(agent_id, call_id)` MCP tool
   - **Reject button** → Opens dialog to enter rejection reason
   - **Reject with reason** → Calls `reject_tool_call(agent_id, call_id, reason)` MCP tool
   - Optimistic UI updates (immediate removal from list)
   - Auto-refresh after action completes

4. **Live Updates**
   - Attempts to subscribe to `resource://approvals/pending` for push updates
   - Falls back to polling (5-second interval) if subscriptions unavailable
   - Graceful error handling with user-friendly messages

5. **TypeScript Compliance**
   - Uses generated types from `src/generated/types.ts` (`PendingApproval`)
   - Proper type imports from `@modelcontextprotocol/sdk`
   - Full type safety throughout

### ⚠️ Backend Requirements

The component requires the following backend infrastructure to be fully functional:

#### 1. MCP StreamableHTTP Endpoint (REQUIRED)

The MCP bridge server (`adgn.agent.mcp_bridge.servers.agents`) needs to be exposed via HTTP. Currently it only runs internally.

**Required changes:**
- Mount the MCP bridge server at `/api/mcp` with StreamableHTTP transport
- Accept bearer token authentication (frontend sends via `getOrExtractToken()`)
- Example mounting code (needs to be added to `server/app.py`):
  ```python
  from fastmcp.server.streamable_http import StreamableHTTPServerTransport

  # In create_app()
  mcp_bridge = app.state.mcp_bridge_registry  # Get the bridge server
  transport = StreamableHTTPServerTransport("/api/mcp")
  app.mount("/api/mcp", transport.handle_request)
  ```

#### 2. Resource Subscriptions (OPTIONAL)

The backend MCP server currently broadcasts `ResourceUpdated` notifications, but StreamableHTTP subscription support needs to be verified. If not available:
- The component falls back to polling (already implemented)
- Subscriptions can be added later for real-time push updates

## Usage

### Import and Mount

```svelte
<script>
  import GlobalApprovalsList from './components/GlobalApprovalsList.svelte'
</script>

<div class="container">
  <GlobalApprovalsList />
</div>
```

### Authentication

The component uses `getOrExtractToken()` from `shared/token` to:
1. Check localStorage for saved token
2. Extract token from URL query params if present
3. Auto-save extracted tokens for future use

Ensure the user is authenticated before mounting this component.

## Component Architecture

### State Management

```typescript
// Approvals data
approvals: Array<PendingApproval & { agent_id: string }> = []

// Grouped by agent_id for display
$: groupedApprovals = approvals.reduce(...)

// UI state
loading: boolean
error: string | null
expandedApprovals: Set<string>  // Track which args are expanded

// Rejection dialog
showRejectDialog: boolean
rejectCallId: string
rejectAgentId: string
rejectReason: string
```

### MCP Client Lifecycle

1. **Initialization** (`initializeMCP`)
   - Creates MCP client with credentials
   - Subscribes to resource updates (if supported)
   - Starts polling fallback
   - Fetches initial data

2. **Resource Fetching** (`fetchApprovals`)
   - Reads `resource://approvals/pending`
   - Parses array of `TextResourceContents`
   - Extracts JSON from each block's `text` field
   - Updates reactive state

3. **Cleanup** (`onDestroy`)
   - Clears polling interval
   - Closes MCP client connection

### Error Handling

The component gracefully handles:
- Missing MCP endpoint (404) → Shows helpful setup message
- Authentication failures → Clear error message
- Resource read failures → Displays error, retries on next poll
- Tool call failures → Shows error, doesn't remove from list

## MCP Resources and Tools

### Resource: `resource://approvals/pending`

**Returns:** Array of `TextResourceContents`

Each block structure:
```json
{
  "uri": "resource://agents/{agent_id}/approvals/{call_id}",
  "mimeType": "application/json",
  "text": "{\"agent_id\":\"...\",\"call_id\":\"...\",\"tool\":\"...\",\"args\":{...},\"timestamp\":\"...\"}"
}
```

### Tool: `approve_tool_call`

**Arguments:**
```typescript
{
  agent_id: string,
  call_id: string
}
```

**Effect:** Approves the tool call, allowing the agent to proceed

### Tool: `reject_tool_call`

**Arguments:**
```typescript
{
  agent_id: string,
  call_id: string,
  reason: string
}
```

**Effect:** Rejects the tool call with a reason, preventing execution

## Styling

The component uses CSS custom properties for theming:
- `--text-primary`, `--muted` - Text colors
- `--border` - Border colors
- `--surface-0`, `--surface-1`, `--surface-2` - Background layers
- `--success-bg`, `--danger-bg`, `--primary-bg` - Button colors
- `--link` - Link/interactive element color
- `--error-bg`, `--error-border`, `--error-text` - Error styling

All colors have fallback defaults for standalone use.

## Future Enhancements

1. **Real-time Subscriptions**
   - Replace polling with WebSocket resource subscriptions
   - Instant updates when approvals are added/resolved

2. **Bulk Actions**
   - Multi-select approvals
   - Approve/reject multiple at once

3. **Filtering and Search**
   - Filter by agent_id
   - Search by tool name
   - Filter by timestamp

4. **Approval History**
   - Show recently approved/rejected items
   - Undo capability for recent actions

5. **Notifications**
   - Browser notifications for new approvals
   - Sound alerts (optional)

## Testing

To test the component:

1. **Backend Setup** (required first):
   ```python
   # Add to server/app.py
   # Mount MCP bridge at /api/mcp with StreamableHTTP
   ```

2. **Start Backend**:
   ```bash
   cd adgn
   adgn-mini-codex serve
   ```

3. **Start Frontend**:
   ```bash
   cd src/adgn/agent/web
   npm run dev
   ```

4. **Create Test Approvals**:
   - Create an agent that makes tool calls requiring approval
   - The approvals should appear in the global list

5. **Verify**:
   - Approvals display correctly grouped by agent
   - Approve/reject actions work
   - List updates after actions
   - Error messages display on failures

## Related Files

- **Backend MCP Server**: `adgn/agent/mcp_bridge/servers/agents.py`
  - Resource: `approvals_pending_global()` (line ~258)
  - Tools: `approve_tool_call()`, `reject_tool_call()` (line ~345)

- **Generated Types**: `src/generated/types.ts`
  - `PendingApproval` interface

- **MCP Client**: `src/features/mcp/client.ts`
  - `createMCPClient()`, `readResource()`, `callTool()`, `subscribeToResource()`

- **Token Management**: `src/shared/token.ts`
  - `getOrExtractToken()`

- **JSON Display**: `src/components/JsonDisclosure.svelte`
  - Used for expandable args display
