<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import type { ApprovalHistoryEntry, ApprovalOutcome } from '../generated/types'
  import { getApprovalHistory } from '../features/agents/api'

  // Props
  export let agentId: string

  // Local state
  let timeline: ApprovalHistoryEntry[] = []
  let filteredTimeline: ApprovalHistoryEntry[] = []
  let loading = true
  let error: string | null = null

  // Filters and controls
  let filterDecision: 'all' | 'approved' | 'rejected' | 'policy' = 'all'
  let searchTool = ''
  let sortOrder: 'newest' | 'oldest' = 'newest'
  let expandedEntries = new Set<string>()

  // Fetch timeline from MCP resource
  async function fetchTimeline() {
    if (!agentId) return

    loading = true
    error = null

    try {
      const data = await getApprovalHistory(agentId)
      timeline = data.timeline || []
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      timeline = []
    } finally {
      loading = false
    }
  }

  /**
   * Parse tool call args_json to object
   */
  function parseArgs(argsJson: string | null): Record<string, unknown> {
    if (!argsJson) return {}
    try {
      return JSON.parse(argsJson)
    } catch {
      return {}
    }
  }

  // Subscribe to live updates via WebSocket
  let ws: WebSocket | null = null

  function subscribeToUpdates() {
    if (!agentId) return

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws/approvals?agent_id=${encodeURIComponent(agentId)}`

      ws = new WebSocket(wsUrl)

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)

          // Handle approval decision messages - add to timeline
          if (msg.type === 'approval_decision') {
            const entry: ApprovalHistoryEntry = {
              tool_call: {
                name: msg.tool || msg.tool_key || 'unknown',
                call_id: msg.call_id,
                args_json: msg.args ? JSON.stringify(msg.args) : null
              },
              outcome: msg.outcome,
              reason: msg.reason || null,
              timestamp: new Date().toISOString()
            }

            // Add to timeline, avoiding duplicates
            timeline = [entry, ...timeline.filter(e => e.tool_call.call_id !== msg.call_id)]
          }

          // Handle history snapshot messages
          if (msg.type === 'approvals_snapshot' && msg.timeline) {
            timeline = msg.timeline
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.onerror = () => {
        console.warn('WebSocket error for approval timeline')
      }

      ws.onclose = () => {
        console.log('WebSocket closed for approval timeline')
      }
    } catch (e) {
      console.error('Failed to create WebSocket:', e)
    }
  }

  function unsubscribe() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  // Filter and sort timeline
  $: {
    let filtered = timeline

    // Filter by decision type
    if (filterDecision === 'approved') {
      filtered = filtered.filter(e =>
        e.outcome === 'user_approve' || e.outcome === 'policy_allow'
      )
    } else if (filterDecision === 'rejected') {
      filtered = filtered.filter(e =>
        e.outcome === 'user_deny_continue' ||
        e.outcome === 'user_deny_abort' ||
        e.outcome === 'policy_deny_continue' ||
        e.outcome === 'policy_deny_abort'
      )
    } else if (filterDecision === 'policy') {
      filtered = filtered.filter(e =>
        e.outcome.startsWith('policy_')
      )
    }

    // Filter by tool name search
    if (searchTool.trim()) {
      const search = searchTool.toLowerCase()
      filtered = filtered.filter(e =>
        e.tool_call.name.toLowerCase().includes(search)
      )
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      const aTime = new Date(a.timestamp).getTime()
      const bTime = new Date(b.timestamp).getTime()
      return sortOrder === 'newest' ? bTime - aTime : aTime - bTime
    })

    filteredTimeline = filtered
  }

  // Toggle argument expansion
  function toggleExpand(callId: string) {
    if (expandedEntries.has(callId)) {
      expandedEntries.delete(callId)
    } else {
      expandedEntries.add(callId)
    }
    expandedEntries = expandedEntries
  }

  // Get color class for decision
  function getDecisionClass(outcome: ApprovalOutcome): string {
    if (outcome === 'policy_allow') return 'auto-approved'
    if (outcome === 'user_approve') return 'user-approved'
    return 'rejected'
  }

  // Get decision label
  function getDecisionLabel(outcome: ApprovalOutcome): string {
    const labels: Record<ApprovalOutcome, string> = {
      'policy_allow': 'AUTO APPROVED',
      'policy_deny_continue': 'POLICY DENIED (CONTINUE)',
      'policy_deny_abort': 'POLICY DENIED (ABORT)',
      'user_approve': 'USER APPROVED',
      'user_deny_continue': 'USER DENIED (CONTINUE)',
      'user_deny_abort': 'USER DENIED (ABORT)'
    }
    return labels[outcome] || outcome
  }

  // Get decision method
  function getDecisionMethod(outcome: ApprovalOutcome): string {
    if (outcome.startsWith('policy_')) return 'AUTO'
    if (outcome.startsWith('user_')) return 'USER'
    return 'UNKNOWN'
  }

  // Format timestamp
  function formatTimestamp(ts: string): string {
    try {
      const date = new Date(ts)
      return date.toLocaleString()
    } catch {
      return ts
    }
  }

  // Format arguments for display
  function formatArgs(args: any): string {
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }

  // Lifecycle
  onMount(() => {
    fetchTimeline()
    subscribeToUpdates()
  })

  onDestroy(() => {
    unsubscribe()
  })

  // Re-fetch when agentId changes
  $: if (agentId) {
    fetchTimeline()
    unsubscribe()
    subscribeToUpdates()
  }
</script>

<div class="timeline-container">
  <div class="timeline-header">
    <h3>Approval Timeline</h3>

    <div class="controls">
      <div class="control-row">
        <label>
          Filter:
          <select bind:value={filterDecision}>
            <option value="all">All Decisions</option>
            <option value="approved">Approved Only</option>
            <option value="rejected">Rejected Only</option>
            <option value="policy">Policy Decisions</option>
          </select>
        </label>

        <label>
          Search:
          <input
            type="text"
            bind:value={searchTool}
            placeholder="Tool name..."
          />
        </label>

        <label>
          Sort:
          <select bind:value={sortOrder}>
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
          </select>
        </label>
      </div>
    </div>
  </div>

  <div class="timeline-content">
    {#if loading}
      <div class="message">Loading timeline...</div>
    {:else if error}
      <div class="error-message">{error}</div>
    {:else if filteredTimeline.length === 0}
      <div class="message">
        {timeline.length === 0 ? 'No approval history yet' : 'No entries match the current filters'}
      </div>
    {:else}
      <div class="timeline">
        {#each filteredTimeline as entry (entry.tool_call.call_id)}
          <div class="timeline-entry {getDecisionClass(entry.outcome)}">
            <div class="entry-header">
              <div class="entry-title">
                <span class="tool-name">{entry.tool_call.name}</span>
                <span class="decision-badge {getDecisionClass(entry.outcome)}">
                  {getDecisionLabel(entry.outcome)}
                </span>
              </div>
              <div class="entry-meta">
                <span class="method-badge">{getDecisionMethod(entry.outcome)}</span>
                <span class="timestamp">{formatTimestamp(entry.timestamp)}</span>
              </div>
            </div>

            <div class="entry-body">
              <div class="entry-detail">
                <span class="label">Call ID:</span>
                <code class="call-id">{entry.tool_call.call_id}</code>
              </div>

              <div class="entry-detail">
                <button
                  class="expand-toggle"
                  on:click={() => toggleExpand(entry.tool_call.call_id)}
                >
                  {expandedEntries.has(entry.tool_call.call_id) ? '▼' : '▶'}
                  Arguments
                </button>

                {#if expandedEntries.has(entry.tool_call.call_id)}
                  <pre class="args-content">{formatArgs(parseArgs(entry.tool_call.args_json))}</pre>
                {/if}
              </div>

              {#if entry.reason}
                <div class="entry-detail reason">
                  <span class="label">Reason:</span>
                  <span class="reason-text">{entry.reason}</span>
                </div>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <div class="timeline-footer">
    <span class="count">
      Showing {filteredTimeline.length} of {timeline.length} entries
    </span>
  </div>
</div>

<style>
  .timeline-container {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--surface);
  }

  .timeline-header {
    padding: 1rem;
    border-bottom: 1px solid var(--border);
  }

  .timeline-header h3 {
    margin: 0 0 0.75rem 0;
    font-size: 1.125rem;
  }

  .controls {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .control-row {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    align-items: center;
  }

  .control-row label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
  }

  .control-row select,
  .control-row input {
    padding: 0.25rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    color: var(--text);
    font-size: 0.875rem;
  }

  .control-row input {
    min-width: 150px;
  }

  .timeline-content {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
  }

  .message,
  .error-message {
    text-align: center;
    padding: 2rem;
    color: var(--muted);
  }

  .error-message {
    color: #b00020;
  }

  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .timeline-entry {
    border: 2px solid var(--border);
    border-radius: 6px;
    padding: 0.75rem;
    background: var(--surface-2);
    transition: border-color 0.2s;
  }

  .timeline-entry.auto-approved {
    border-color: #2ecc71;
  }

  .timeline-entry.user-approved {
    border-color: #3498db;
  }

  .timeline-entry.rejected {
    border-color: #e74c3c;
  }

  .entry-header {
    display: flex;
    justify-content: space-between;
    align-items: start;
    margin-bottom: 0.5rem;
    gap: 0.5rem;
  }

  .entry-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .tool-name {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
    font-weight: 600;
    font-size: 0.875rem;
  }

  .decision-badge {
    padding: 0.125rem 0.5rem;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
  }

  .decision-badge.auto-approved {
    background: #2ecc71;
    color: white;
  }

  .decision-badge.user-approved {
    background: #3498db;
    color: white;
  }

  .decision-badge.rejected {
    background: #e74c3c;
    color: white;
  }

  .entry-meta {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--muted);
  }

  .method-badge {
    padding: 0.125rem 0.375rem;
    background: var(--surface-3);
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.625rem;
  }

  .timestamp {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
  }

  .entry-body {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .entry-detail {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.875rem;
  }

  .entry-detail .label {
    font-weight: 600;
    color: var(--muted);
    font-size: 0.75rem;
  }

  .call-id {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
    font-size: 0.75rem;
    padding: 0.125rem 0.25rem;
    background: var(--surface-3);
    border-radius: 3px;
    align-self: flex-start;
  }

  .expand-toggle {
    padding: 0.25rem 0.5rem;
    background: var(--surface-3);
    border: 1px solid var(--border);
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.75rem;
    font-weight: 600;
    align-self: flex-start;
    transition: background 0.2s;
  }

  .expand-toggle:hover {
    background: var(--surface);
  }

  .args-content {
    padding: 0.5rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.75rem;
    overflow-x: auto;
    margin-top: 0.25rem;
  }

  .entry-detail.reason {
    padding: 0.5rem;
    background: var(--surface);
    border-left: 3px solid #e74c3c;
    border-radius: 4px;
  }

  .reason-text {
    font-style: italic;
    color: var(--text);
  }

  .timeline-footer {
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--border);
    font-size: 0.75rem;
    color: var(--muted);
    text-align: center;
  }

  .count {
    font-weight: 600;
  }
</style>
