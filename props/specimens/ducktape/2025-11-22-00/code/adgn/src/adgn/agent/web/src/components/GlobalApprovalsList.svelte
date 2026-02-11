<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { createMCPClient, readResource, callTool, subscribeToResource } from '../features/mcp/client'
  import { getOrExtractToken } from '../shared/token'
  import type { PendingApproval } from '../generated/types'
  import { MCPUris } from '../generated/mcpConstants'
  import type { Client } from '@modelcontextprotocol/sdk/client/index.js'
  import JsonDisclosure from './JsonDisclosure.svelte'

  // Component state
  let approvals: Array<PendingApproval & { agent_id: string }> = []
  let loading = true
  let error: string | null = null
  let mcpClient: Client | null = null
  let refreshInterval: number | null = null

  // Rejection dialog state
  let showRejectDialog = false
  let rejectCallId = ''
  let rejectAgentId = ''
  let rejectReason = ''

  // Expanded state for args display
  let expandedApprovals = new Set<string>()

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

  // Group approvals by agent_id for display
  $: groupedApprovals = approvals.reduce((acc, approval) => {
    const agentId = approval.agent_id
    if (!acc[agentId]) {
      acc[agentId] = []
    }
    acc[agentId].push(approval)
    return acc
  }, {} as Record<string, Array<PendingApproval & { agent_id: string }>>)

  /**
   * Initialize MCP client and fetch approvals
   *
   * NOTE: This requires the backend to expose an MCP StreamableHTTP endpoint.
   * The current backend doesn't expose this yet - the MCP bridge server
   * exists but isn't mounted at an HTTP endpoint accessible from the frontend.
   *
   * To enable this, the backend would need to:
   * 1. Mount the MCP bridge server at an HTTP endpoint (e.g., /api/mcp)
   * 2. Use FastMCP's StreamableHTTP transport
   * 3. Accept bearer token authentication
   */
  async function initializeMCP() {
    try {
      const token = getOrExtractToken()
      if (!token) {
        throw new Error('No authentication token available')
      }

      // Connect to MCP server (requires backend to expose MCP endpoint)
      // In a full implementation, this would connect to something like:
      // http://localhost:8765/api/mcp
      mcpClient = await createMCPClient({
        name: 'global-approvals-ui',
        url: `${window.location.origin}/api/mcp`,
        token
      })

      // Subscribe to resource updates for live refresh
      // NOTE: Subscription support would need to be added to the backend
      try {
        await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
      } catch (e) {
        console.warn('Subscription not supported, will use polling:', e)
      }

      // Initial fetch
      await fetchApprovals()

      // Poll for updates (fallback if subscriptions not available)
      refreshInterval = window.setInterval(fetchApprovals, 5000)

    } catch (e) {
      error = `Failed to connect to MCP server: ${e instanceof Error ? e.message : String(e)}`
      console.error('MCP initialization error:', e)

      // For development: if MCP endpoint doesn't exist, show helpful message
      if (e instanceof Error && e.message.includes('404')) {
        error += '\n\nThe backend MCP endpoint is not yet exposed. This component requires the MCP bridge server to be mounted at /api/mcp with StreamableHTTP transport.'
      }
    } finally {
      loading = false
    }
  }

  /**
   * Fetch all pending approvals from the global mailbox
   *
   * The resource://approvals/pending resource returns multiple TextResourceContents blocks,
   * where each block contains a JSON-serialized approval.
   */
  async function fetchApprovals() {
    if (!mcpClient) return

    try {
      // Read the global approvals resource
      const contents = await readResource(mcpClient, MCPUris.approvalsPendingUri)

      // Parse contents - it returns an array of TextResourceContents
      // Each block has: { uri, mimeType, text }
      // The text field contains JSON with: { agent_id, tool_call: { name, call_id, args_json }, timestamp }
      const parsedApprovals: Array<PendingApproval & { agent_id: string }> = []

      for (const block of contents) {
        if ('text' in block && block.mimeType === 'application/json') {
          try {
            const data = JSON.parse(block.text)
            parsedApprovals.push({
              agent_id: data.agent_id,
              tool_call: data.tool_call,
              timestamp: data.timestamp
            })
          } catch (parseError) {
            console.error('Failed to parse approval block:', parseError, block)
          }
        }
      }

      approvals = parsedApprovals
      error = null

    } catch (e) {
      error = `Failed to fetch approvals: ${e instanceof Error ? e.message : String(e)}`
      console.error('Fetch error:', e)
    }
  }

  /**
   * Approve a tool call via MCP tool
   */
  async function handleApprove(agentId: string, callId: string) {
    if (!mcpClient) return

    try {
      // Call MCP tool: approve_tool_call(agent_id, call_id)
      await callTool(mcpClient, 'approve_tool_call', {
        agent_id: agentId,
        call_id: callId
      })

      // Remove from local state immediately for responsive UI
      approvals = approvals.filter(a => !(a.agent_id === agentId && a.tool_call.call_id === callId))

      // Refresh to get updated state
      await fetchApprovals()

    } catch (e) {
      error = `Failed to approve: ${e instanceof Error ? e.message : String(e)}`
      console.error('Approve error:', e)
    }
  }

  /**
   * Show rejection dialog
   */
  function showRejectDialogFor(agentId: string, callId: string) {
    rejectAgentId = agentId
    rejectCallId = callId
    rejectReason = ''
    showRejectDialog = true
  }

  /**
   * Reject a tool call via MCP tool with reason
   */
  async function handleReject() {
    if (!mcpClient || !rejectReason.trim()) return

    try {
      // Call MCP tool: reject_tool_call(agent_id, call_id, reason)
      await callTool(mcpClient, 'reject_tool_call', {
        agent_id: rejectAgentId,
        call_id: rejectCallId,
        reason: rejectReason
      })

      // Remove from local state
      approvals = approvals.filter(a => !(a.agent_id === rejectAgentId && a.tool_call.call_id === rejectCallId))

      // Close dialog
      showRejectDialog = false
      rejectCallId = ''
      rejectAgentId = ''
      rejectReason = ''

      // Refresh to get updated state
      await fetchApprovals()

    } catch (e) {
      error = `Failed to reject: ${e instanceof Error ? e.message : String(e)}`
      console.error('Reject error:', e)
    }
  }

  function toggleExpanded(agentId: string, callId: string) {
    const key = `${agentId}:${callId}`
    if (expandedApprovals.has(key)) {
      expandedApprovals.delete(key)
    } else {
      expandedApprovals.add(key)
    }
    expandedApprovals = expandedApprovals
  }

  function isExpanded(agentId: string, callId: string): boolean {
    return expandedApprovals.has(`${agentId}:${callId}`)
  }

  // Lifecycle
  onMount(() => {
    initializeMCP()
  })

  onDestroy(() => {
    if (refreshInterval) {
      window.clearInterval(refreshInterval)
    }
    if (mcpClient) {
      // Close MCP connection if needed
      // The SDK Client might have a close() method
    }
  })
</script>

<div class="global-approvals">
  <h3>Global Approvals Mailbox</h3>

  {#if loading}
    <div class="status">Loading...</div>
  {:else if error}
    <div class="error">
      <strong>Error:</strong>
      <pre>{error}</pre>
    </div>
  {:else if approvals.length === 0}
    <div class="empty">No pending approvals</div>
  {:else}
    <div class="approvals-list">
      {#each Object.entries(groupedApprovals) as [agentId, agentApprovals]}
        <div class="agent-group">
          <h4>Agent: <code>{agentId}</code> ({agentApprovals.length} pending)</h4>

          {#each agentApprovals as approval}
            <div class="approval-card">
              <div class="approval-header">
                <div class="tool-info">
                  <strong>{approval.tool_call.name}</strong>
                  <span class="call-id">({approval.tool_call.call_id.slice(0, 8)}...)</span>
                </div>
                <div class="timestamp">{new Date(approval.timestamp).toLocaleString()}</div>
              </div>

              <div class="approval-body">
                <button
                  class="expand-toggle"
                  on:click={() => toggleExpanded(agentId, approval.tool_call.call_id)}
                >
                  {isExpanded(agentId, approval.tool_call.call_id) ? '▼' : '▶'} Arguments
                </button>

                {#if isExpanded(agentId, approval.tool_call.call_id)}
                  <div class="args-display">
                    <JsonDisclosure label="Tool Arguments" value={parseArgs(approval.tool_call.args_json)} open={true} />
                  </div>
                {/if}
              </div>

              <div class="approval-actions">
                <button
                  class="btn-approve"
                  on:click={() => handleApprove(agentId, approval.tool_call.call_id)}
                >
                  Approve
                </button>
                <button
                  class="btn-reject"
                  on:click={() => showRejectDialogFor(agentId, approval.tool_call.call_id)}
                >
                  Reject
                </button>
              </div>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  {/if}
</div>

{#if showRejectDialog}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="modal-backdrop" on:click={() => showRejectDialog = false}>
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="modal-content" on:click|stopPropagation>
      <h3>Reject Tool Call</h3>
      <p>
        Agent: <code>{rejectAgentId}</code><br>
        Call ID: <code>{rejectCallId}</code>
      </p>

      <label for="reject-reason">Reason for rejection:</label>
      <textarea
        id="reject-reason"
        bind:value={rejectReason}
        placeholder="Enter reason for rejection..."
        rows="4"
      ></textarea>

      <div class="modal-actions">
        <button
          class="btn-primary"
          on:click={handleReject}
          disabled={!rejectReason.trim()}
        >
          Confirm Reject
        </button>
        <button
          class="btn-secondary"
          on:click={() => showRejectDialog = false}
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .global-approvals {
    padding: 1rem;
    height: 100%;
    overflow-y: auto;
  }

  h3 {
    margin: 0 0 1rem 0;
    font-size: 1.25rem;
  }

  h4 {
    margin: 0.5rem 0;
    font-size: 1rem;
    color: var(--text-primary, #333);
  }

  .status, .empty {
    color: var(--muted, #666);
    font-style: italic;
  }

  .error {
    background: var(--error-bg, #fee);
    border: 1px solid var(--error-border, #fcc);
    padding: 0.75rem;
    border-radius: 4px;
    color: var(--error-text, #c00);
  }

  .error pre {
    margin: 0.5rem 0 0 0;
    white-space: pre-wrap;
    font-size: 0.85rem;
  }

  .approvals-list {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .agent-group {
    border: 1px solid var(--border, #ddd);
    border-radius: 4px;
    padding: 0.75rem;
    background: var(--surface-1, #fafafa);
  }

  .approval-card {
    background: var(--surface-0, #fff);
    border: 1px solid var(--border, #ddd);
    border-radius: 4px;
    padding: 0.75rem;
    margin: 0.5rem 0;
  }

  .approval-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }

  .tool-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .call-id {
    color: var(--muted, #666);
    font-size: 0.85rem;
    font-family: monospace;
  }

  .timestamp {
    font-size: 0.85rem;
    color: var(--muted, #666);
  }

  .approval-body {
    margin: 0.5rem 0;
  }

  .expand-toggle {
    background: none;
    border: none;
    color: var(--link, #0066cc);
    cursor: pointer;
    padding: 0.25rem 0;
    font-size: 0.9rem;
  }

  .expand-toggle:hover {
    text-decoration: underline;
  }

  .args-display {
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: var(--surface-2, #f5f5f5);
    border-radius: 4px;
    font-family: monospace;
    font-size: 0.85rem;
    max-height: 300px;
    overflow-y: auto;
  }

  .approval-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
  }

  .btn-approve, .btn-reject {
    padding: 0.5rem 1rem;
    border-radius: 4px;
    border: 1px solid transparent;
    cursor: pointer;
    font-size: 0.9rem;
  }

  .btn-approve {
    background: var(--success-bg, #28a745);
    color: white;
    border-color: var(--success-border, #1e7e34);
  }

  .btn-approve:hover {
    background: var(--success-hover, #218838);
  }

  .btn-reject {
    background: var(--danger-bg, #dc3545);
    color: white;
    border-color: var(--danger-border, #c82333);
  }

  .btn-reject:hover {
    background: var(--danger-hover, #c82333);
  }

  /* Modal styles */
  .modal-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal-content {
    background: var(--surface-0, white);
    padding: 1.5rem;
    border-radius: 8px;
    max-width: 500px;
    width: 90%;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }

  .modal-content h3 {
    margin: 0 0 1rem 0;
  }

  .modal-content p {
    margin: 0 0 1rem 0;
  }

  .modal-content label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
  }

  .modal-content textarea {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid var(--border, #ddd);
    border-radius: 4px;
    font-family: inherit;
    resize: vertical;
  }

  .modal-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
    justify-content: flex-end;
  }

  .btn-primary, .btn-secondary {
    padding: 0.5rem 1rem;
    border-radius: 4px;
    border: 1px solid transparent;
    cursor: pointer;
    font-size: 0.9rem;
  }

  .btn-primary {
    background: var(--primary-bg, #007bff);
    color: white;
    border-color: var(--primary-border, #0056b3);
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--primary-hover, #0056b3);
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: var(--secondary-bg, #6c757d);
    color: white;
    border-color: var(--secondary-border, #545b62);
  }

  .btn-secondary:hover {
    background: var(--secondary-hover, #545b62);
  }
</style>
