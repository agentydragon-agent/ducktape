<script lang="ts">
  import { createPatch } from 'diff'
  import type { Proposal } from '../shared/types'
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import hljs from 'highlight.js/lib/common'
  import { getProposal } from '../features/agents/api'
  import { currentAgentId } from '../features/agents/stores'

  export let proposal: Proposal
  export let showActions: boolean = false
  export let onApprove: ((id: string) => void) | undefined
  export let onReject: ((id: string) => void) | undefined

  type DiffLine = { cls: 'add'|'del'|'hunk'|'meta'|'ctx'; text: string }

  function normalizePolicy(src: string): string {
    let t = (src || '').replaceAll('\r\n', '\n').replaceAll('\r', '\n')
    t = t.replace(/[ \t]+$/gm, '')
    if (t.length === 0) return t
    t = t.replace(/\n+$/g, '') + '\n'
    return t
  }

  let source: string | null = null
  let loadError: string | null = null
  let highlighted: string = ''
  onMount(async () => {
    const agentId = get(currentAgentId) as string | null
    if (!agentId) { loadError = 'No agent selected'; return }
    const rec = await getProposal(agentId, proposal.id)
    source = rec.content
    try { highlighted = hljs.highlight(source || '', { language: 'python' }).value } catch { highlighted = source || '' }
  })
</script>

<div class="proposal">
  <div class="proposal-header">
    <strong>#{proposal.id}</strong>
    {#if proposal.status}
      <span class="badge">{proposal.status}</span>
    {/if}
  </div>
  {#if source}
    <details class="proposal-source" open>
      <summary>Proposal source</summary>
      <pre class="policy-content"><code class="hljs language-python">{@html highlighted}</code></pre>
    </details>
  {:else if loadError}
    <div class="error">{loadError}</div>
  {/if}
  {#if showActions}
    <div class="row">
      <button on:click={() => onApprove && onApprove(proposal.id)}>Approve</button>
      <button on:click={() => onReject && onReject(proposal.id)}>Withdraw</button>
    </div>
  {/if}
</div>

<style>
  .proposal { border: 1px solid var(--border); padding: 0.75rem; margin: 0.5rem 0; border-radius: 4px; }
  .proposal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  /* Removed unused .proposal-docstring */
  .badge { font-size: 0.7rem; padding: 0.05rem 0.3rem; border-radius: 2px; margin-left: 0.25rem; }
  .badge { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
  .policy-content { background: var(--surface-2); padding: 0.5rem; overflow: auto; max-height: 12rem; font-size: 0.75rem; }
  .error { color: #b00020; font-size: 0.8rem; }
</style>
