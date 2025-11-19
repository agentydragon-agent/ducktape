# ApprovalTimeline Component Usage

## Overview

The `ApprovalTimeline` component displays historical approval decisions for an agent, with live updates and filtering capabilities.

## Component Location

`src/components/ApprovalTimeline.svelte`

## Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `agentId` | `string` | Yes | The ID of the agent whose timeline to display |

## Features

### Data Fetching
- Fetches initial timeline via HTTP GET `/api/agents/{agentId}/approvals/history`
- Returns `AgentApprovalsHistory` with `timeline: ApprovalHistoryEntry[]`

### Live Updates
- Subscribes to WebSocket at `/ws/agents/{agentId}/approvals`
- Listens for `approval_decision` messages
- Automatically updates timeline when new decisions are made

### Display
Each timeline entry shows:
- **Tool name** - The name of the tool that was called
- **Decision type** - Approval/rejection status with color coding:
  - 🟢 Green: `policy_allow` (AUTO approved)
  - 🔵 Blue: `user_approve` (USER approved)
  - 🔴 Red: Rejected (any deny outcome)
- **Decision method** - AUTO or USER badge
- **Timestamp** - When the decision was made
- **Call ID** - Unique identifier for the tool call
- **Arguments** - Expandable JSON view of tool arguments
- **Rejection reason** - Shown if decision was rejected

### Filtering & Search
- **Filter by decision type:**
  - All Decisions
  - Approved Only
  - Rejected Only
  - Policy Decisions
- **Search by tool name** - Type-ahead filter
- **Sort order:**
  - Newest First (default)
  - Oldest First

### Color Coding
- **Green border** - Auto-approved by policy
- **Blue border** - Approved by user
- **Red border** - Rejected (by user or policy)

## Example Usage

### Basic Integration

```svelte
<script lang="ts">
  import ApprovalTimeline from './components/ApprovalTimeline.svelte'
  import { currentAgentId } from './shared/router'
</script>

{#if $currentAgentId}
  <ApprovalTimeline agentId={$currentAgentId} />
{/if}
```

### In a Tab Panel

```svelte
<script lang="ts">
  import ApprovalTimeline from './components/ApprovalTimeline.svelte'
  import { currentAgentId } from './shared/router'

  let activeTab: 'approvals' | 'timeline' | 'settings' = 'approvals'
</script>

<div class="tabs">
  <button class:active={activeTab === 'approvals'} on:click={() => activeTab = 'approvals'}>
    Pending Approvals
  </button>
  <button class:active={activeTab === 'timeline'} on:click={() => activeTab = 'timeline'}>
    Timeline
  </button>
  <button class:active={activeTab === 'settings'} on:click={() => activeTab = 'settings'}>
    Settings
  </button>
</div>

<div class="tab-content">
  {#if activeTab === 'timeline' && $currentAgentId}
    <ApprovalTimeline agentId={$currentAgentId} />
  {/if}
  <!-- Other tab content -->
</div>
```

### With Error Handling

```svelte
<script lang="ts">
  import ApprovalTimeline from './components/ApprovalTimeline.svelte'
  import { currentAgentId } from './shared/router'

  $: agentId = $currentAgentId
</script>

{#if agentId}
  <ApprovalTimeline {agentId} />
{:else}
  <div class="error">No agent selected</div>
{/if}
```

## API Endpoint

The component expects a backend endpoint:

**GET** `/api/agents/{agentId}/approvals/history`

**Response:**
```json
{
  "agent_id": "string",
  "timeline": [
    {
      "call_id": "string",
      "tool": "string",
      "args": {},
      "outcome": "user_approve" | "policy_allow" | "user_deny_continue" | "user_deny_abort" | "policy_deny_continue" | "policy_deny_abort",
      "reason": "string | null",
      "timestamp": "ISO 8601 datetime string"
    }
  ],
  "pending": [],
  "count": 0
}
```

## WebSocket Messages

The component subscribes to approval decision messages:

```json
{
  "type": "approval_decision",
  "call_id": "string",
  "tool": "string",
  "args": {},
  "outcome": "user_approve",
  "reason": null,
  "timestamp": "2025-11-19T12:34:56Z"
}
```

And approval snapshots:

```json
{
  "type": "approvals_snapshot",
  "timeline": [ /* array of ApprovalHistoryEntry */ ]
}
```

## Styling

The component uses CSS custom properties for theming:
- `--surface` - Background color
- `--surface-2` - Entry background
- `--surface-3` - Subtle backgrounds
- `--border` - Border color
- `--text` - Text color
- `--muted` - Muted text color

## Notes

- The component automatically handles agent ID changes
- WebSocket connections are cleaned up on component destroy
- Empty states show appropriate messages
- Loading states are indicated
- Errors are displayed to the user

## Future Enhancements

Potential improvements:
- Export timeline to CSV/JSON
- Advanced filtering (by date range, decision method)
- Grouping by tool or time period
- Pagination for very long timelines
- Search in arguments (not just tool names)
- Statistics/summary view
