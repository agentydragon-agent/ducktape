local I = import '../../specimens/lib.libsonnet';

// iss-050: ApprovalTimeline subscribes to unimplemented WebSocket endpoint

I.issueOneOccurrence(
  rationale= |||
    The `ApprovalTimeline.svelte` component attempts to subscribe to a WebSocket
    endpoint (`/ws/approvals`) that doesn't exist in the backend, resulting in
    non-functional live updates.

    **Problem: Frontend subscribes to non-existent endpoint**

    **Current implementation (ApprovalTimeline.svelte, lines 54-61):**
    ```typescript
    function subscribeToUpdates() {
      if (!agentId) return

      try {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const wsUrl = `${protocol}//${window.location.host}/ws/approvals?agent_id=${encodeURIComponent(agentId)}`

        ws = new WebSocket(wsUrl)
        // ... message handlers
      } catch (e) {
        console.error('Failed to create WebSocket:', e)
      }
    }
    ```

    **Expected WebSocket messages (lines 64-87):**
    ```typescript
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)

      // Handle approval decision messages
      if (msg.type === 'approval_decision') {
        const entry: ApprovalHistoryEntry = {
          tool_call: { name: msg.tool || msg.tool_key || 'unknown', ... },
          outcome: msg.outcome,
          reason: msg.reason || null,
          timestamp: new Date().toISOString()
        }
        timeline = [entry, ...timeline]
      }

      // Handle history snapshot messages
      if (msg.type === 'approvals_snapshot' && msg.timeline) {
        timeline = msg.timeline
      }
    }
    ```

    **Backend status:** WebSocket routes are not registered. The `/ws/approvals` endpoint doesn't exist (app.py has TODO placeholder).

    **Why this is problematic:**

    1. **Non-functional feature**: Component appears to work but doesn't receive updates
    2. **Silent failure**: WebSocket connection fails, no user feedback
    3. **Misleading UX**: UI suggests live updates work when they don't
    4. **Wasted resources**: Attempts connection that always fails
    5. **Incomplete implementation**: Frontend built for feature backend doesn't provide

    **The correct approach depends on intent:**

    **Option 1: Implement the backend** — Add WebSocket endpoint with event subscription (send initial snapshot, then stream approval decisions with call_id/tool/outcome/reason/timestamp).

    **Option 2: Remove WebSocket code** — Replace subscribeToUpdates() with polling (setInterval every 5s).

    **Option 3: Use MCP subscriptions** — Subscribe to approval timeline resource via MCP client instead of custom WebSocket (fits 2-level compositor architecture better).

    **Current silent failure behavior:** Lines 92-98 handle WebSocket errors with console.warn/log only — users have no indication that live updates aren't working.

    **Better error handling if keeping WebSocket:** Show user feedback ("Live updates unavailable") or fall back to polling automatically on connection failure.

    **User's instruction: "ApprovalTimeline subscribes to a websockets. check if
    it's implemented. if it isn't, upsert issue."**

    **Status:** WebSocket endpoint `/ws/approvals` is **not implemented**. Backend
    has TODO placeholder but no actual endpoint.

    **Recommendation:**

    1. **Short term**: Remove WebSocket code, use polling or MCP subscriptions
    2. **Long term**: If WebSocket is needed, implement backend endpoint
    3. **Best**: Use MCP resource subscriptions (fits architecture)

    **Why this happened:**

    1. Frontend component built expecting WebSocket endpoint
    2. Backend WebSocket routes marked as TODO
    3. Feature left partially implemented
    4. No error surfaced to user or developers
    5. Component appears functional but isn't

    **Similar issues:**

    - GlobalApprovalsList expects `/api/mcp` endpoint that may not exist (issue 047)
    - Multiple components assume backend features not yet implemented
    - Silent failures hide incomplete implementation
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte': [
      [54, 61],   // WebSocket subscription to non-existent endpoint
      [92, 98],   // Silent error/close handlers
    ],
    'adgn/src/adgn/agent/server/app.py': [
      [1, 1],     // TODO placeholder for WebSocket routes (actual line varies)
    ],
  },
)
