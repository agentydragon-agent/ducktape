<script lang="ts">
  type Pending = { call_id: string; tool_key: string; args_json?: string | null }

  export let pending: Pending[] = []

  export let approvalPolicy: { content: string; version: number; proposals?: Array<{id: string, status: string, rationale?: string, source: string}> } | null = null
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

  // Pretty unified diff using the 'diff' library
  import { createPatch } from 'diff'
  type DiffLine = { cls: 'add'|'del'|'hunk'|'meta'|'ctx'; text: string }
  // Normalize policy text to reduce noisy diffs while preserving significant indentation.
  // - Normalize line endings to \n
  // - Strip trailing spaces/tabs on each line
  // - Ensure a single trailing newline at EOF
  function normalizePolicy(src: string): string {
    let t = src.replaceAll('\r\n', '\n').replaceAll('\r', '\n')
    t = t.replace(/[ \t]+$/gm, '')
    if (t.length === 0) return t
    // Ensure exactly one trailing newline for stable patches
    t = t.replace(/\n+$/g, '') + '\n'
    return t
  }
  function renderUnifiedDiff(a: string, b: string): DiffLine[] {
    const aN = normalizePolicy(a)
    const bN = normalizePolicy(b)
    const patch = createPatch('policy.py', aN, bN, 'current', 'proposal', { context: 3 })
    const lines = patch.split('\n')
    const out: DiffLine[] = []
    for (const line of lines) {
      if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) out.push({ cls: 'meta', text: line })
      else if (line.startsWith('@@')) out.push({ cls: 'hunk', text: line })
      else if (line.startsWith('+')) out.push({ cls: 'add', text: line })
      else if (line.startsWith('-')) out.push({ cls: 'del', text: line })
      else out.push({ cls: 'ctx', text: line })
    }
    return out
  }

  // Split proposals into open and past for display
  $: allProposals = approvalPolicy?.proposals || []
  $: openProposals = allProposals.filter(p => p.status === 'open')
  $: pastProposals = allProposals.filter(p => p.status !== 'open')

  // Sort past proposals newest-first. Prefer numeric order for ids like "p-<n>"; fallback to lexicographic desc.
  function seqFromId(id: string): number | null {
    const m = /^p-(\d+)$/.exec(id)
    return m ? parseInt(m[1], 10) : null
  }
  $: pastProposalsSorted = [...pastProposals].sort((a, b) => {
    const sa = seqFromId(a.id)
    const sb = seqFromId(b.id)
    if (sa != null && sb != null) return sb - sa
    if (sa != null) return -1
    if (sb != null) return 1
    // Fallback: reverse lexicographic so "larger" ids appear first
    return String(b.id).localeCompare(String(a.id))
  })
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
      <textarea bind:value={editingPolicy} rows="15" placeholder="def decide(ctx): ..." class="policy-editor"></textarea>
      <div class="row">
        <button on:click={() => { setPolicy(editingPolicy); cancelEditingPolicy(); }}>Save</button>
        <button on:click={cancelEditingPolicy}>Cancel</button>
      </div>
    {/if}
  </div>

  {#if allProposals.length > 0}
    <div class="proposals">
      {#if openProposals.length > 0}
      <h4>Open Proposals ({openProposals.length})</h4>
      {#each openProposals as proposal}
        <div class="proposal">
          <div class="proposal-header">
            <strong>#{proposal.id}</strong>
            <span class="proposal-status status-{proposal.status}">{proposal.status}</span>
          </div>
          {#if proposal.rationale}
            <div class="proposal-rationale">{proposal.rationale}</div>
          {/if}
          <details class="proposal-source">
            <summary>Diff vs current policy</summary>
            <div class="policy-content diff">
              {#each renderUnifiedDiff(approvalPolicy?.content || '', proposal.source || '') as d}
                <div class="line {d.cls}">{d.text}</div>
              {/each}
            </div>
          </details>
          <div class="row">
            <button on:click={() => approveProposal(proposal.id)}>Approve</button>
            <button on:click={() => rejectProposal(proposal.id)}>Reject</button>
          </div>
        </div>
      {/each}
      {/if}
      {#if pastProposalsSorted.length > 0}
        <details class="past-proposals">
          <summary>Past Proposals ({pastProposalsSorted.length})</summary>
          {#each pastProposalsSorted as proposal}
            <div class="proposal">
              <div class="proposal-header">
                <strong>#{proposal.id}</strong>
                <span class="proposal-status status-{proposal.status}">{proposal.status}</span>
              </div>
              {#if proposal.rationale}
                <div class="proposal-rationale">{proposal.rationale}</div>
              {/if}
              <details class="proposal-source">
                <summary>Diff vs current policy</summary>
                <div class="policy-content diff">
                  {#each renderUnifiedDiff(approvalPolicy?.content || '', proposal.source || '') as d}
                    <div class="line {d.cls}">{d.text}</div>
                  {/each}
                </div>
              </details>
            </div>
          {/each}
        </details>
      {/if}
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
  .proposal { border: 1px solid var(--border); padding: 0.75rem; margin: 0.5rem 0; border-radius: 4px; }
  .proposal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  .proposal-status { font-size: 0.75rem; padding: 0.2rem 0.4rem; border-radius: 0.75rem; text-transform: uppercase; font-weight: 500; }
  .status-open { background: #e3f2fd; color: #1976d2; }
  .status-approved { background: #e8f5e8; color: #2e7d32; }
  .status-rejected { background: #ffebee; color: #c62828; }
  .status-withdrawn { background: #f5f5f5; color: #757575; }
  .proposal-rationale { color: #555; font-style: italic; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .proposal-source { margin: 0.5rem 0; }
  .proposal-source summary { cursor: pointer; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.25rem; }
  .policy-content.diff { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.75rem; line-height: 1.25; padding: 0.5rem; background: var(--surface-2); border-left: 3px solid var(--border); }
  .policy-content.diff .line.add { color: #2e7d32; }
  .policy-content.diff .line.del { color: #c62828; }
  .policy-content.diff .line.ctx { color: var(--text); opacity: 0.85; }
  /* Past proposals: reduce visual weight */
  .past-proposals .proposal { padding: 0.5rem; margin: 0.25rem 0; }
</style>
