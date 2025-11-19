# Chat Inbox Architecture (MCP-Native)

This document describes the chat inbox architecture using MCP resources for message delivery between humans and agents. It covers resource patterns, UI server integration, frontend subscriptions, and end-to-end message delivery flows.

See also:
- `mcp-runtime/ui-chat.md` — detailed MCP protocol specifications and sequences
- `mcp-runtime/resources.md` — resources server and subscriptions management
- `mcp-runtime/overview.md` — runtime architecture overview

---

## Architecture Overview

The chat inbox is implemented as an MCP resource exposed by a dedicated `chat` server (UI server), with dual subscriptions (orchestrator + frontend). This eliminates tight coupling between the agent runtime and UI while maintaining real-time message delivery.

### Key Components

1. **Chat Server** (MCP) — Sidecar server handling human ↔ agent messaging
   - Exposes `ui://chat/inbox` resource (append-only message stream)
   - Emits `notifications/resources/updated` for new messages
   - Provides tools: `chat_read_since`, `chat.human.post`, `chat.assistant.post`

2. **Orchestrator** — Pinned subscriber consuming user messages for agent context
   - Maintains watermark (`last_id`) for crash/restart recovery
   - Injects new user messages as `UserText` events into agent sampling
   - Does **not** self-echo assistant messages (server suppresses notifications)

3. **Frontend (UI)** — Optional subscriber rendering messages in timeline
   - Subscribes to resource updates or periodic reads
   - Receives messages via notifications or `resources/read`
   - Renders timeline from current `UiState` (single source of truth)

---

## MCP Resource Pattern

### Resource Definition

**URI:** `ui://chat/inbox`

**MIME Type:** `application/json`

**Body (JSON):**
```json
{
  "last_id": "1700000012345",
  "messages": [
    {
      "id": "1700000012344",
      "ts": "2025-10-09T12:34:50Z",
      "author": "user",
      "mime": "text/markdown",
      "content": "CI is green on main"
    },
    {
      "id": "1700000012345",
      "ts": "2025-10-09T12:34:56Z",
      "author": "user",
      "mime": "text/markdown",
      "content": "Deploy now?"
    }
  ]
}
```

### Message Fields

- **id**: Monotonically increasing, time-ordered identifier (ULID, Snowflake, or ISO-8601 with sequence)
  - Used for watermarking and exactly-once delivery semantics
  - Opaque to clients; treated as ordered token
- **ts**: ISO-8601 timestamp (e.g., `2025-10-09T12:34:50Z`)
- **author**: `"user"` or `"assistant"` — distinguishes human from agent messages
- **mime**: Content type (typically `"text/markdown"` or `"text/plain"`)
- **content**: Message body (markdown, text, or structured)

### Resource Semantics

- **Append-only**: Once a message is published with an `id`, it is immutable and permanent
- **Identity**: Each message has a precise, monotonic `id` that is the single source of truth for ordering
- **No self-echo**: Agent-authored messages do NOT trigger notifications (prevents duplicate consumption)
- **High-water mark**: Clients use `last_id` as a watermark for crash/restart recovery

---

## MCP Notifications

### Notification Format

Server emits `notifications/resources/updated` when new user messages arrive:

```json
{
  "method": "notifications/resources/updated",
  "params": {
    "uri": "ui://chat/inbox",
    "messages": [
      {
        "id": "1700000012346",
        "ts": "2025-10-09T12:35:00Z",
        "author": "user",
        "mime": "text/markdown",
        "content": "Ship it!"
      }
    ]
  }
}
```

### Notification Semantics

- Emitted **only for user messages** — never for agent responses
- May include a small `messages[]` batch for automation efficiency (optional)
- Dual subscribers handle the notification independently:
  - **Orchestrator** (pinned): must consume **every** message (no skipping); persists new `last_id`
  - **UI**: optional; can ignore notification details and call `resources/read` for full fidelity

---

## Tools (Chat Server)

### `chat_read_since`

Deterministic, stateless catch-up after restart/reconnect.

**Input:**
```json
{
  "after_id": "1700000012344",
  "limit": 50
}
```

**Output:**
```json
{
  "messages": [
    { "id": "1700000012345", "ts": "...", "author": "user", "mime": "text/markdown", "content": "..." },
    { "id": "1700000012346", "ts": "...", "author": "user", "mime": "text/markdown", "content": "..." }
  ],
  "last_id": "1700000012346"
}
```

**Semantics:**
- Returns all messages with `id > after_id` (strictly after the watermark)
- Respects `limit` (default: all remaining)
- Stateless on the server; client is responsible for persisting watermark
- Used by orchestrator for recovery and pagination

### `chat.human.post`

Human message submission (from UI or external source).

**Input:**
```json
{
  "mime": "text/markdown",
  "content": "What's the deployment status?"
}
```

**Output:**
```json
{
  "id": "1700000012347",
  "ts": "2025-10-09T12:35:10Z"
}
```

**Semantics:**
- Appends to inbox; returns assigned `id` and `ts`
- Triggers `notifications/resources/updated uri=ui://chat/inbox`
- No suppression; humans always see their own messages immediately (local echo or server notification)

### `chat.assistant.post`

Agent message submission (called by runtime instead of `ui.send_message`).

**Input:**
```json
{
  "mime": "text/markdown",
  "content": "Deployment in progress. ETA: 2 minutes."
}
```

**Output:**
```json
{
  "id": "1700000012348",
  "ts": "2025-10-09T12:35:15Z"
}
```

**Semantics:**
- Appends to inbox with `author: "assistant"`
- **Does NOT trigger notifications** (no self-echo)
- Runtime emits an `AssistantMarkdownItem` to `UiState` so frontend updates immediately
- Human/UI clients see the message via periodic `resources/read` or local echo (not via notifications)

---

## Frontend Integration Guide

### Subscription Setup

The frontend uses MCP subscription manager to receive real-time updates:

```typescript
import { getMCPClient } from '../mcp/clientManager'
import { createSubscriptionManager } from '../mcp/subscriptions'

async function subscribeToChat(agentId: string) {
  const client = await getMCPClient()
  const subMgr = createSubscriptionManager(client)

  await subMgr.subscribe('ui://chat/inbox', (data) => {
    if (data.error) {
      console.error('Chat resource error:', data.message)
      return
    }

    // Parse JSON resource content
    const inbox = JSON.parse(data[0].text)

    // Update UI state with messages
    updateChatTimeline(inbox.messages)
  })
}
```

### Component Integration

The **MessageComposer** component displays when both conditions are met:

1. **UI server is available**: Check `$agentStatus.ui?.ready === true`
2. **Local + UI agent mode**: Verify agent type is `local` or `ui`

Example:

```typescript
import MessageComposer from './MessageComposer.svelte'

let agentStatus: AgentStatus
let isReadyToChat = false

$: isReadyToChat =
  agentStatus?.ui?.ready === true &&
  ['local', 'ui'].includes(agentStatus.type)
```

### Timeline Rendering

Chat messages appear in the `ApprovalTimeline` component, merged with other UI state items (approvals, tool results, etc.):

- **User messages** render as `UserTextItem` (author: "user")
- **Assistant messages** render as `AssistantMarkdownItem` (author: "assistant")
- **Order**: By timestamp (`ts`) and `id` for tie-breaking

---

## Message Delivery Flow (Sequence Diagrams)

### User Message Flow (Human → Agent)

```
┌──────────┐         ┌─────────────┐         ┌──────────────┐         ┌──────────┐
│ Frontend │         │ Chat Server │         │ Orchestrator │         │  Agent   │
└────┬─────┘         └──────┬──────┘         └──────┬───────┘         └────┬─────┘
     │                       │                       │                      │
     │ POST chat.human.post  │                       │                      │
     │──────────────────────>│                       │                      │
     │                       │                       │                      │
     │                       │ append to inbox       │                      │
     │                       │ emit notifications/   │                      │
     │                       │ resources/updated     │                      │
     │                       │───────────────────────>                      │
     │                       │                       │                      │
     │                       │ (no self-echo)        │ receive notification │
     │<──────────────────────│                       │ call chat_read_since │
     │ {id, ts} response     │                       │ persist last_id      │
     │                       │                       │ emit UserText event  │
     │ local echo displays   │                       │───────────────────────>
     │ immediately           │                       │                  inject
     │                       │                       │                  into
     │                       │                       │                  sampling
     │                       │                       │                      │
     │                       │                       │<────────────────────
     │                       │         Agent response (calls chat.assistant.post)
     │                       │
```

### Agent Message Flow (Agent → Frontend)

```
┌──────────────┐         ┌─────────────┐         ┌──────────┐
│ Orchestrator │         │ Chat Server │         │ Frontend │
└──────┬───────┘         └──────┬──────┘         └────┬─────┘
       │                         │                     │
       │ chat.assistant.post     │                     │
       │────────────────────────>│                     │
       │                         │                     │
       │                         │ append to inbox     │
       │                         │ (no notification    │
       │                         │  -- no self-echo)   │
       │                         │                     │
       │ {id, ts} response       │                     │
       │<────────────────────────│                     │
       │                         │                     │
       │ emit AssistantMarkdown  │                     │
       │ Item to UiState         │                     │
       │                         │                     │
       │                         │<─────────────────────
       │                         │ (periodic read or
       │                         │  new subscription)
       │                         │ resources/read      │
       │                         │ returns current     │
       │                         │ inbox (includes     │
       │                         │ assistant message)  │
       │                         │────────────────────>
       │                         │ update timeline     │
       │                         │                     │
```

### Startup/Hydration Flow

```
┌──────────────┐         ┌─────────────┐         ┌──────────┐
│ Orchestrator │         │ Chat Server │         │ Frontend │
└──────┬───────┘         └──────┬──────┘         └────┬─────┘
       │                         │                     │
       │ subscribe pinned        │                     │
       │────────────────────────>│                     │
       │                         │ subscribe (pinned)  │
       │ (enable chat mode)      │ stored in DB        │
       │                         │                     │
       │ read_since(after_id)    │                     │
       │ or resources/read       │                     │
       │────────────────────────>│                     │
       │ {messages, last_id}     │                     │
       │<────────────────────────│                     │
       │ persist last_id         │                     │
       │ inject all messages     │                     │
       │ (no skipping)           │                     │
       │                         │                     │ subscribe (optional)
       │                         │                     │────────────────────>
       │                         │                     │ subscribe OK
       │                         │                     │<────────────────────
       │                         │                     │
       │                         │                     │ resources/read
       │                         │                     │────────────────────>
       │                         │ current inbox       │
       │                         │<────────────────────│
       │                         │                     │ render timeline
       │                         │                     │ from UiState
       │                         │                     │
```

### Crash/Reconnect Flow

```
┌──────────────┐         ┌─────────────┐
│ Orchestrator │         │ Chat Server │
└──────┬───────┘         └──────┬──────┘
       │                         │
       │ RESTART                 │
       │ (persisted last_id)     │
       │                         │
       │ chat_read_since(        │
       │   after_id=PERSISTED)   │
       │────────────────────────>│
       │                         │
       │ {messages, last_id}     │
       │<────────────────────────│
       │ (all messages after     │
       │  persisted ID)          │
       │                         │
       │ inject all messages     │
       │ (no skipping)           │
       │ persist new last_id     │
       │                         │
```

---

## High-Water Marks (Watermarking)

### Orchestrator-Managed Watermarks

The orchestrator maintains a stable, persisted `last_id` for exactly-once delivery:

1. **Startup**: Load persisted `last_id` from storage (SQLite `resource_watermarks` table)
2. **On notification**: Receive `notifications/resources/updated` → call `chat_read_since({after_id: last_id})`
3. **Inject messages**: For each message, emit a `UserText` event (ordered, no skipping)
4. **Persist**: Store the new `last_id` after all messages for this batch are scheduled
5. **Crash recovery**: On restart, use the persisted `last_id` to call `chat_read_since` and resume

### Frontend Watermarking (Optional)

The frontend may optionally track reads independently:

- **Stateless read**: Call `resources/read` periodically; no persistence needed
- **Persistent read**: Store `last_read_id` and call `chat_read_since` for pagination
- **Subscription-only**: Subscribe to notifications and rely on server batches; no read_since needed

---

## UI Server Integration

### Availability Detection

Check if the UI server is ready before displaying chat components:

```typescript
// From agent status
const uiReady = agentStatus?.ui?.ready === true

// Shows MessageComposer + chat timeline only if true
{#if uiReady}
  <MessageComposer on:submit={handleSendMessage} />
  <ApprovalTimeline items={timelineItems} />
{/if}
```

### Resource Availability

When UI server is available, these resources are accessible via MCP:

- `ui://chat/inbox` — Append-only message stream
- `ui://agent/status` — UI server health/readiness
- Other UI state resources as defined by the UI server spec

### Error Handling

On UI server unavailability:

- Chat components are hidden
- Existing timeline remains visible (read-only)
- Subscriptions gracefully degrade: reconnect on server return
- Error messages in `$lastError` store help diagnose issues

---

## Subscriber Identity

### Orchestrator Identity

- Uses a **dedicated, stable token** if needed for server access control
- Watermarking does **not** rely on server-managed identity
- Preferred: bind token at server start; rotate carefully to maintain HWM continuity

### Frontend (UI) Identity

- Optional **separate token** (e.g., `subscriber=human`)
- Multiple clients may share a token (shared view) or use distinct tokens (independent views per device/tab)
- Independent of orchestrator watermark; UI reads for "latest" state only

### Token Rotation

- Keep tokens stable across reconnects for persistent watermarks
- If tokens rotate, ensure mapping to previous subscriber identity to restore HWM context
- Tools may accept optional `subscriber` parameter for administrative reads or backfills

---

## Comparison with Legacy UI Server

### V1 (Bus-Only, Deprecated)

- In-process event bus (`send_message`, `end_turn`)
- Tight coupling between runtime and UI
- No resource subscriptions or notifications
- Watermarking handled implicitly by the runtime

### V2+ (MCP-Native, Target)

- Dedicated chat server with resource + notifications
- Loose coupling; dual subscriptions (orchestrator + UI)
- Explicit watermarking with persisted HWMs
- Supports multiple concurrent subscribers
- Cleaner separation of concerns (chat server, orchestrator, UI)

**Migration path**: Gradual switchover; V1 bus remains supported temporarily alongside MCP resources.

---

## Example: MessageComposer Component

```typescript
// src/adgn/agent/web/src/components/MessageComposer.svelte

<script lang="ts">
  import { currentAgentId } from '../stores'
  import { agentStatus } from '../stores'

  let message = ''
  let isLoading = false

  async function handleSend() {
    if (!message.trim()) return

    isLoading = true
    try {
      // Call chat.human.post MCP tool
      const response = await fetch('/api/mcp/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server: 'ui',
          tool: 'chat.human.post',
          arguments: { mime: 'text/markdown', content: message }
        })
      })

      const result = await response.json()
      if (result.error) throw new Error(result.error)

      // Clear input; server notification will update timeline
      message = ''
    } finally {
      isLoading = false
    }
  }
</script>

{#if $agentStatus?.ui?.ready}
  <div class="message-composer">
    <textarea
      bind:value={message}
      placeholder="Send a message..."
      disabled={isLoading}
    />
    <button on:click={handleSend} disabled={isLoading || !message.trim()}>
      Send
    </button>
  </div>
{/if}
```

---

## Testing the Chat Inbox

### Manual Testing Steps

1. **Start the runtime** with chat server enabled
   ```bash
   adgn-mini-codex serve --mcp-config chat-server.json
   ```

2. **Subscribe to the resource** (or let frontend do it automatically)
   ```python
   # In Python, using FastMCP client
   await client.subscribeResource({ "uri": "ui://chat/inbox" })
   ```

3. **Send a human message**
   ```bash
   # Via REST API or tool call
   curl -X POST http://localhost:8765/api/tools/ui_chat_human_post \
     -d '{"mime": "text/markdown", "content": "Hello!"}'
   ```

4. **Observe notifications** and timeline updates in both orchestrator logs and frontend

5. **Verify watermarks** persisted correctly after restart

### Automated Tests

See `tests/` for:
- Subscription manager tests (resource refresh, notification handling)
- UI state reducer tests (chat item integration)
- End-to-end chat flows (posting, subscribing, rendering)

---

## Key Takeaways

1. **Resource-first**: Chat is delivered as an MCP resource (`ui://chat/inbox`), not a special case
2. **Dual subscriptions**: Orchestrator (pinned, watermarked) and frontend (optional, read-only)
3. **No self-echo**: Agent messages do NOT trigger notifications; runtime emits `AssistantMarkdownItem` instead
4. **Exactly-once delivery**: Orchestrator uses persisted `last_id` for crash/restart recovery
5. **Loose coupling**: Chat server is independent; multiple UI implementations can subscribe
6. **Graceful degradation**: UI works without chat; frontend hides composer if server unavailable

---

## See Also

- `mcp-runtime/ui-chat.md` — Detailed MCP protocol specs and message sequences
- `mcp-runtime/resources.md` — Resources server architecture and subscriptions
- `mcp-runtime/overview.md` — Full runtime architecture overview
- `mcp-runtime/matrix.md` — Similar pattern for Matrix server integration
- Frontend source: `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/chat/`
