<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import hljs from 'highlight.js/lib/common'
  import ProposalCard from './ProposalCard.svelte'
  import type { ApprovalPolicyInfo, Proposal } from '../shared/types'

  // Props
  export let agentId: string

  // Local state
  let approvalPolicy: ApprovalPolicyInfo | null = null
  let showPolicyEditor = false
  let editingPolicy = ''
  let loading = true
  let error: string | null = null
  let allProposals: Proposal[] = []

  // Reactive
  $: allProposals = approvalPolicy?.proposals || []

  // Syntax highlighting for current policy (Python)
  function renderHighlightedPython(src: string): string {
    try {
      return hljs.highlight(src, { language: 'python' }).value
    } catch {
      return src
    }
  }

  // Fetch policy from API
  async function fetchPolicy() {
    if (!agentId) return

    loading = true
    error = null

    try {
      const origin = window.location.origin
      const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy`
      const res = await fetch(url)

      if (!res.ok) {
        throw new Error(`Failed to fetch policy: ${res.status}`)
      }

      approvalPolicy = await res.json()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      approvalPolicy = null
    } finally {
      loading = false
    }
  }

  // Save policy
  async function savePolicy() {
    if (!agentId || !editingPolicy) return

    try {
      const origin = window.location.origin
      const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy`
      const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editingPolicy })
      })

      if (!res.ok) {
        throw new Error(`Failed to save policy: ${res.status}`)
      }

      // Refresh policy after save
      await fetchPolicy()
      showPolicyEditor = false
      editingPolicy = ''
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  // Approve proposal
  async function approveProposal(proposalId: string) {
    if (!agentId) return

    try {
      const origin = window.location.origin
      const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy/proposals/${encodeURIComponent(proposalId)}/approve`
      const res = await fetch(url, { method: 'POST' })

      if (!res.ok) {
        throw new Error(`Failed to approve proposal: ${res.status}`)
      }

      // Refresh policy after approval
      await fetchPolicy()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  // Reject proposal
  async function rejectProposal(proposalId: string) {
    if (!agentId) return

    try {
      const origin = window.location.origin
      const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy/proposals/${encodeURIComponent(proposalId)}/reject`
      const res = await fetch(url, { method: 'POST' })

      if (!res.ok) {
        throw new Error(`Failed to reject proposal: ${res.status}`)
      }

      // Refresh policy after rejection
      await fetchPolicy()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  function startEditingPolicy() {
    editingPolicy = approvalPolicy?.content || ''
    showPolicyEditor = true
  }

  function cancelEditingPolicy() {
    showPolicyEditor = false
    editingPolicy = ''
  }

  // Lifecycle
  onMount(() => {
    fetchPolicy()
  })

  // Watch for agent ID changes
  $: if (agentId) {
    fetchPolicy()
  }
</script>

<div class="policy-editor-pane">
  <h3>Policy Editor</h3>

  {#if loading}
    <div class="loading">Loading policy...</div>
  {:else if error}
    <div class="error">{error}</div>
  {/if}

  <div class="policy-section">
    <h4>
      Approval Policy
      {#if approvalPolicy}
        <small>(v{approvalPolicy.id})</small>
      {/if}
    </h4>

    {#if !showPolicyEditor}
      {#if approvalPolicy}
        <pre class="policy-content"><code class="hljs language-python">{@html renderHighlightedPython(approvalPolicy.content)}</code></pre>
        <button on:click={startEditingPolicy} class="edit-btn">Edit Policy</button>
      {:else}
        <div class="empty">No policy loaded</div>
      {/if}
    {:else}
      <textarea
        bind:value={editingPolicy}
        rows="20"
        placeholder="# Program reads PolicyRequest from stdin and prints PolicyResponse&#10;# See adgn.agent.policies.scaffold.run(decide)"
        class="policy-editor"
      ></textarea>
      <div class="button-row">
        <button on:click={savePolicy} class="save-btn">Save</button>
        <button on:click={cancelEditingPolicy} class="cancel-btn">Cancel</button>
      </div>
    {/if}
  </div>

  {#if allProposals.length > 0}
    <div class="proposals-section">
      <h4>Policy Proposals ({allProposals.length})</h4>
      {#each allProposals as proposal}
        <ProposalCard
          {proposal}
          showActions={true}
          onApprove={(id) => approveProposal(id)}
          onReject={(id) => rejectProposal(id)}
        />
      {/each}
      <button class="view-all-btn">View All</button>
    </div>
  {/if}
</div>

<style>
  .policy-editor-pane {
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: 1rem;
    background: var(--surface);
    border-left: 1px solid var(--border);
  }

  h3 {
    margin: 0 0 1rem 0;
    font-size: 1.1rem;
    color: var(--text);
  }

  h4 {
    margin: 0.5rem 0 0.5rem 0;
    font-size: 0.95rem;
    color: var(--text);
  }

  h4 small {
    color: var(--muted);
    font-weight: normal;
  }

  .loading,
  .error,
  .empty {
    padding: 0.5rem;
    color: var(--muted);
    font-size: 0.9rem;
  }

  .error {
    color: #b00020;
  }

  .policy-section {
    margin-bottom: 1.5rem;
  }

  .policy-content {
    background: var(--surface-2);
    padding: 0.75rem;
    overflow: auto;
    max-height: 20rem;
    font-size: 0.8rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    margin: 0.5rem 0;
  }

  .policy-editor {
    width: 100%;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
    font-size: 0.8rem;
    resize: vertical;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    color: var(--text);
    min-height: 300px;
  }

  .button-row {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  button {
    padding: 0.4rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    color: var(--text);
    cursor: pointer;
    font-size: 0.9rem;
  }

  button:hover {
    background: var(--surface-3);
  }

  .save-btn {
    background: #2ecc71;
    color: white;
    border-color: #27ae60;
  }

  .save-btn:hover {
    background: #27ae60;
  }

  .cancel-btn {
    background: var(--surface-2);
  }

  .edit-btn {
    margin-top: 0.5rem;
  }

  .proposals-section {
    margin-top: 1.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
  }

  .view-all-btn {
    margin-top: 0.5rem;
    width: 100%;
  }
</style>
