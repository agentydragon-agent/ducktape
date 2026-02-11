<script lang="ts">
  import type { ApprovalPolicyInfo, Proposal } from '../shared/types'
  import type { Pending } from '../features/chat/stores'

  export let pending: Pending[] = []

  export let approvalPolicy: ApprovalPolicyInfo | null = null
  export let showPolicyEditor = false
  export let editingPolicy = ''

  // Callbacks provided by parent
  export let startEditingPolicy: () => void
  export let cancelEditingPolicy: () => void
  export let setPolicy: (content: string) => void
  export let approveProposal: (id: string) => void
  export let rejectProposal: (id: string) => void
  export let approve: (call_id: string) => void
  export let denyContinue: (call_id: string) => void
  export let deny: (call_id: string) => void

  function prettyArgs(args_json?: string | null) {
    if (!args_json) return ''
    try { return JSON.stringify(JSON.parse(args_json), null, 2) } catch { return args_json }
  }

  // Syntax highlighting for current policy (Python)
  import hljs from 'highlight.js/lib/common'
  function renderHighlightedPython(src: string): string {
    try { return hljs.highlight(src, { language: 'python' }).value } catch { return src }
  }

  import ProposalCard from './ProposalCard.svelte'

  // Split proposals into open and past for display
  let allProposals: Proposal[] = []
  $: allProposals = approvalPolicy?.proposals || []
</script>

<div class="approvals-tab">
  <div class="policy">
    <h4>Approval Policy {#if approvalPolicy}<small>(v{approvalPolicy.version})</small>{/if}</h4>
    {#if !showPolicyEditor}
      {#if approvalPolicy}
        <pre class="policy-content"><code class="hljs language-python">{@html renderHighlightedPython(approvalPolicy.content)}</code></pre>
        <button on:click={startEditingPolicy}>Edit Policy</button>
      {:else}
        <div class="empty">No policy loaded</div>
      {/if}
    {:else}
      <textarea bind:value={editingPolicy} rows="15" placeholder="# Program reads PolicyRequest from stdin and prints PolicyResponse\n# See adgn.agent.policies.scaffold.run(decide)" class="policy-editor"></textarea>
      <div class="row">
        <button on:click={() => { setPolicy(editingPolicy); cancelEditingPolicy(); }}>Save</button>
        <button on:click={cancelEditingPolicy}>Cancel</button>
      </div>
    {/if}
  </div>

  {#if allProposals.length > 0}
    <div class="proposals">
      <h4>Open Proposals ({allProposals.length})</h4>
      {#each allProposals as proposal}
        <ProposalCard {proposal}
          showActions={true}
          onApprove={(id) => approveProposal(id)}
          onReject={(id) => rejectProposal(id)} />
      {/each}
    </div>
  {/if}

  <div class="approvals">
    <h4>Pending Approvals ({pending.length})</h4>
    {#if pending.length === 0}
      <div class="empty">None</div>
    {:else}
      {#each pending as p}
        <div class="approval">
          <div><code>{p.tool_key}</code> <small>({p.call_id})</small></div>
          {#if p.args_json}
            <pre class="pre">{prettyArgs(p.args_json)}</pre>
          {/if}
          <div class="row">
            <button on:click={() => approve(p.call_id)}>Approve</button>
            <button on:click={() => denyContinue(p.call_id)}>Deny (continue)</button>
            <button on:click={() => deny(p.call_id)}>Deny (abort)</button>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .approvals-tab h4 { margin: 0.25rem 0; }
  .policy-content { background: var(--surface-2); padding: 0.5rem; overflow: auto; max-height: 12rem; font-size: 0.75rem; }
  .policy-editor { width: 100%; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.75rem; resize: vertical; }
  .approval { border: 1px solid var(--border); padding: 0.5rem; margin: 0.25rem 0; }
  .row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .empty { color: var(--muted); }
  /* Removed unused diff styles */
</style>
