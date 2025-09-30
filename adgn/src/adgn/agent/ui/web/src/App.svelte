<script lang="ts">
  import { onMount } from 'svelte'
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'
  // @ts-ignore - library ships no types
  import JSONFormatter from 'json-formatter-js'

  // Collapsible JSON view action for ToolJson items
  function jsonView(node: HTMLElement, value: any) {
    const prefersDark = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    const render = (val: any) => {
      node.innerHTML = ''
      let parsed: any = null
      if (val && typeof val === 'object') parsed = val
      else if (typeof val === 'string') {
        try { parsed = JSON.parse(val) } catch { parsed = null }
      }
      if (parsed && typeof parsed === 'object') {
        const fmt = new (JSONFormatter as any)(parsed, 1, { theme: prefersDark ? 'dark' : undefined, hoverPreviewEnabled: true })
        node.appendChild(fmt.render())
      } else {
        const pre = document.createElement('pre')
        pre.className = 'pre'
        pre.textContent = typeof val === 'string' ? val : String(val)
        node.appendChild(pre)
      }
    }
    render(value)
    return { update: (v: any) => render(v) }
  }

  type Pending = { call_id: string; tool_key: string; args_json?: string | null }

  let ws: WebSocket | null = null
  let connected = false
  let status: string = 'idle'
  let prompt = ''
  let pending = new Map<string, Pending>()
  let mcpServers: string[] = []
  let mcpTools: any[] = []
  let serverExpandedState = new Map<string, boolean>()
  let toolExpandedState = new Map<string, boolean>()
  let lastError: string | null = null
  let messagesEl: HTMLDivElement | null = null
  let promptEl: HTMLTextAreaElement | null = null
  let renderMarkdown = true
  let uiState: any = null
  let approvalPolicy: { content: string; version: number; proposals?: Array<{id: string, status: string, rationale?: string, source: string}> } | null = null
  let policyProposal: { id: string; content: string; rationale?: string } | null = null
  let showPolicyEditor = false
  let activeTab = 'approvals'
  let editingPolicy = ''
  let sidebarWidth = 280

  // Persist settings reactively
  $: try { localStorage.setItem('renderMarkdown', JSON.stringify(renderMarkdown)) } catch {}
  $: try { localStorage.setItem('sidebarWidth', JSON.stringify(sidebarWidth)) } catch {}

  // Load saved sidebar width
  onMount(() => {
    try {
      const saved = localStorage.getItem('sidebarWidth')
      if (saved) sidebarWidth = JSON.parse(saved)
    } catch {}
  })

  // Resize functionality
  let isResizing = false
  function startResize() {
    isResizing = true
    document.addEventListener('mousemove', handleResize)
    document.addEventListener('mouseup', stopResize)
  }

  function handleResize(e: MouseEvent) {
    if (!isResizing) return
    const newWidth = window.innerWidth - e.clientX
    sidebarWidth = Math.max(200, Math.min(500, newWidth))
  }

  function stopResize() {
    isResizing = false
    document.removeEventListener('mousemove', handleResize)
    document.removeEventListener('mouseup', stopResize)
  }


  function connect() {
    const backend = (import.meta as any)?.env?.VITE_BACKEND_ORIGIN || window.location.origin
    const wsProto = backend.startsWith('https') ? 'wss' : 'ws'
    const wsUrl = backend.replace(/^https?/, wsProto) + '/ws'
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      connected = true
      sendJson({ type: 'hello' })
    }
    ws.onmessage = (ev) => {
      try {
        const env = JSON.parse(ev.data)
        const payload = env?.payload ?? env
        handlePayload(payload)
      } catch (e) {
        console.error('invalid WS message', e)
      }
    }
    ws.onerror = (ev) => {
      console.error('ws error', ev)
      lastError = 'WebSocket error (see console)'
    }
    ws.onclose = (ev) => {
      connected = false
      console.warn('ws closed', ev.code, ev.reason)
      lastError = `WS closed: code=${ev.code} reason=${ev.reason || ''}`
    }
  }

  function sendJson(obj: any) {
    ws?.send(JSON.stringify(obj))
  }

  function handlePayload(p: any) {
    const t = p?.type
    if (!t) return
    switch (t) {
      case 'snapshot':
        mcpServers = (p.mcp_servers || []).map((s: any) => s.name)
        mcpTools = p.sampling?.tools || []
        if (p.run_state?.status) status = p.run_state.status
        // Seed pending approvals from snapshot
        if (p.run_state?.pending_approvals?.length) {
          const map = new Map<string, Pending>()
          for (const a of p.run_state.pending_approvals) {
            map.set(a.call_id, {
              call_id: a.call_id,
              tool_key: a.tool_key,
              args_json: JSON.stringify(a.args)
            })
          }
          pending = map
        } else {
          pending = new Map(pending)
        }
        // Update approval policy
        if (p.approval_policy) {
          approvalPolicy = p.approval_policy
        }
        break
      case 'ui_state_snapshot':
        uiState = p.state
        requestAnimationFrame(() => { if (stickToBottom) scrollToBottom() })
        break
      case 'ui_state_updated':
        uiState = p.state
        requestAnimationFrame(() => { if (stickToBottom) scrollToBottom() })
        break
      case 'run_status':
        status = p.run_state?.status || status
        break
      case 'user_text':
      case 'assistant_text':
      case 'tool_call':
      case 'function_call_output':
      case 'reasoning':
      case 'ui_message':
        // Legacy per-event display path disabled; UiState drives rendering now
        break
      case 'approval_pending':
        pending.set(p.call_id, {
          call_id: p.call_id,
          tool_key: p.tool_key,
          args_json: p.args_json ?? null
        })
        pending = new Map(pending)
        break
      case 'approval_decision':
        pending.delete(p.call_id)
        pending = new Map(pending)
        // UiState-driven; no transcript update
        break
      case 'accepted':
        break
      case 'error':
        lastError = `${p.code}: ${p.message}`
        break
      default:
        console.warn('Unknown payload type', t, p)
    }
  }

  function approve(call_id: string) {
    sendJson({ type: 'approve', call_id })
  }

  function denyContinue(call_id: string) {
    sendJson({ type: 'deny_continue', call_id })
  }

  function deny(call_id: string) {
    sendJson({ type: 'deny', call_id })
  }

  function approveProposal(proposalId: string) {
    sendJson({ type: 'apply_proposal', proposal_id: proposalId, decision: 'approve' })
  }

  function rejectProposal(proposalId: string) {
    sendJson({ type: 'apply_proposal', proposal_id: proposalId, decision: 'reject' })
  }

  function setPolicy(content: string) {
    sendJson({ type: 'set_policy', content })
    showPolicyEditor = false
  }

  function startEditingPolicy() {
    editingPolicy = approvalPolicy?.content || ''
    showPolicyEditor = true
  }

  function cancelEditingPolicy() {
    showPolicyEditor = false
    editingPolicy = ''
  }

  function sendPrompt() {
    if (!prompt.trim()) return
    lastError = null
    sendJson({ type: 'send', text: prompt })
    prompt = ''
  }

  function prettyArgs(args_json?: string | null) {
    if (!args_json) return ''
    try {
      return JSON.stringify(JSON.parse(args_json), null, 2)
    } catch {
      return args_json
    }
  }

  // Legacy seatbelt helpers removed; UI renders from UiState only

  // Track whether user is near the bottom; only autoscroll then
  let stickToBottom = true
  function onMessagesScroll() {
    if (!messagesEl) return
    const { scrollTop, scrollHeight, clientHeight } = messagesEl
    stickToBottom = scrollTop + clientHeight >= scrollHeight - 8
  }
  function scrollToBottom() {
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight
  }

  onMount(() => {
    connect()
    requestAnimationFrame(() => { promptEl?.focus() })
    // Load persisted settings
    try {
      const s = localStorage.getItem('renderMarkdown')
      if (s != null) renderMarkdown = JSON.parse(s) === true
    } catch {}
  })
</script>

<main class="shell" style="grid-template-columns: 1fr {sidebarWidth}px">
  <section class="chat">
    {#if lastError}
      <div class="error">Error: {lastError}</div>
    {/if}

    <div class="messages" bind:this={messagesEl} on:scroll={onMessagesScroll}>
      {#if !uiState || !(uiState.items && uiState.items.length)}
        <div class="empty">No messages yet.</div>
      {:else}
        {#each uiState.items as it}
          <div class="msg">
            <div class="kind">{it.kind}</div>
            {#if it.kind === 'UserMessage'}
              <div class="text">{it.text}</div>
            {:else if it.kind === 'AssistantMarkdown'}
              {#if renderMarkdown}
                <div class="text md">{@html DOMPurify.sanitize(marked.parse(it.md || ''))}</div>
              {:else}
                <div class="text">{it.md}</div>
              {/if}
            {:else if it.kind === 'EndTurn'}
              <div class="end-turn-separator"></div>
            {:else if it.kind === 'Tool'}
              {#if it.content?.content_kind === 'Exec'}
                <div class="terminal">
                  <div class="kind">{it.tool} {#if it.decision}<span class="term-approval">[{it.decision}]</span>{/if}</div>
                  <div class="terminal-body">
                    {#if it.content.cmd}
                      <pre class="term-line">$ {it.content.cmd}</pre>
                    {/if}
                    {#if it.content.stdout}
                      <pre class="term-stdout">{it.content.stdout}</pre>
                    {/if}
                    {#if it.content.stderr}
                      <pre class="term-stderr">{it.content.stderr}</pre>
                    {/if}
                    {#if it.content.exit_code !== null && it.content.exit_code !== undefined}
                      <div class="term-exit">[exit {it.content.exit_code}]</div>
                    {/if}
                    {#if it.content.is_error}
                      <div class="term-error">[error]</div>
                    {/if}
                  </div>
                </div>
              {:else if it.content?.content_kind === 'Json'}
                <div class="tool">
                  <strong>{it.tool} {#if it.decision}<span class="term-approval">[{it.decision}]</span>{/if}</strong>
                  {#if it.content.args}
                    <details>
                      <summary>Arguments</summary>
                      <div use:jsonView={it.content.args}></div>
                    </details>
                  {/if}
                  {#if it.content.result}
                    <details open>
                      <summary>Output {#if it.content.is_error}<span class="term-error">[error]</span>{/if}</summary>
                      <div use:jsonView={it.content.result}></div>
                    </details>
                  {/if}
                </div>
              {/if}
            {/if}
          </div>
        {/each}
      {/if}
    </div>

    <form class="composer" on:submit|preventDefault={sendPrompt}>
      <textarea
        bind:this={promptEl}
        bind:value={prompt}
        rows="3"
        placeholder="Type a prompt… (Enter to send, Shift+Enter for newline)"
        on:keydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendPrompt();
          }
        }}
      ></textarea>
      <button type="submit" disabled={!connected}>Send</button>
    </form>
  </section>

  <aside class="sidebar">
    <div class="resize-handle" on:mousedown={startResize}></div>

    <div class="sidebar-header">
      <div class="ws">
        <span class="dot {connected ? 'on' : 'off'}"></span>
        <span>{connected ? 'connected' : 'disconnected'}</span>
      </div>
      <div class="status">Status: {status}</div>
    </div>

    <div class="tabs">
      <button class="tab {activeTab === 'approvals' ? 'active' : ''}" on:click={() => activeTab = 'approvals'}>
        Approvals
        {#if pending.size > 0}<span class="badge">{pending.size}</span>{/if}
      </button>
      <button class="tab {activeTab === 'servers' ? 'active' : ''}" on:click={() => activeTab = 'servers'}>
        Servers ({mcpServers.length})
      </button>
      <button class="tab {activeTab === 'settings' ? 'active' : ''}" on:click={() => activeTab = 'settings'}>
        Settings
      </button>
    </div>

    <div class="tab-content">
      {#if activeTab === 'approvals'}
        <div class="approvals-tab">
          <div class="policy">
            <h4>Approval Policy {#if approvalPolicy}<small>(v{approvalPolicy.version})</small>{/if}</h4>
            {#if !showPolicyEditor}
              {#if approvalPolicy}
                <pre class="policy-content">{approvalPolicy.content}</pre>
                <button on:click={startEditingPolicy}>Edit Policy</button>
              {:else}
                <div class="empty">No policy loaded</div>
              {/if}
            {:else}
              <textarea
                bind:value={editingPolicy}
                rows="15"
                placeholder="def decide(ctx): ..."
                class="policy-editor"
              ></textarea>
              <div class="row">
                <button on:click={() => setPolicy(editingPolicy)}>Save</button>
                <button on:click={cancelEditingPolicy}>Cancel</button>
              </div>
            {/if}
          </div>

          <!-- Policy Proposals Section -->
          {#if approvalPolicy?.proposals && approvalPolicy.proposals.length > 0}
            <div class="proposals">
              <h4>Policy Proposals ({approvalPolicy.proposals.length})</h4>
              {#each approvalPolicy.proposals as proposal}
                <div class="proposal">
                  <div class="proposal-header">
                    <strong>#{proposal.id}</strong>
                    <span class="proposal-status status-{proposal.status}">{proposal.status}</span>
                  </div>
                  {#if proposal.rationale}
                    <div class="proposal-rationale">{proposal.rationale}</div>
                  {/if}
                  <details class="proposal-source">
                    <summary>View proposed policy code</summary>
                    <pre class="policy-content">{proposal.source}</pre>
                  </details>
                  {#if proposal.status === 'open'}
                    <div class="row">
                      <button on:click={() => approveProposal(proposal.id)}>Approve</button>
                      <button on:click={() => rejectProposal(proposal.id)}>Reject</button>
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}

          <div class="approvals">
            <h4>Pending Approvals ({pending.size})</h4>
            {#if pending.size === 0}
              <div class="empty">None</div>
            {:else}
              {#each Array.from(pending.values()) as p}
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
      {:else if activeTab === 'servers'}
        <div class="servers">
          <h4>MCP Servers</h4>
          {#if mcpServers.length}
            {#each mcpServers as serverName}
              {@const serverTools = mcpTools.filter(t => t.name.startsWith(`mcp__${serverName}__`))}
              <div class="server-item">
                <div class="server-header" on:click={() => {
                  serverExpandedState.set(serverName, !serverExpandedState.get(serverName))
                  serverExpandedState = serverExpandedState
                }}>
                  <span class="disclosure">{serverExpandedState.get(serverName) ? '▼' : '▶'}</span>
                  <span class="server-name">{serverName}</span>
                  <span class="tool-count">({serverTools.length} tools)</span>
                </div>
                {#if serverExpandedState.get(serverName)}
                  <div class="tools-list">
                    {#each serverTools as tool}
                      {@const toolKey = tool.name}
                      <div class="tool-item">
                        <div class="tool-header" on:click={() => {
                          toolExpandedState.set(toolKey, !toolExpandedState.get(toolKey))
                          toolExpandedState = toolExpandedState
                        }}>
                          <span class="disclosure">{toolExpandedState.get(toolKey) ? '▼' : '▶'}</span>
                          <span class="tool-name">{tool.name.replace(`mcp__${serverName}__`, '')}</span>
                        </div>
                        {#if toolExpandedState.get(toolKey)}
                          <div class="tool-details">
                            {#if tool.description}
                              <div class="tool-description">{tool.description}</div>
                            {/if}
                            <div class="tool-schema">
                              <div class="schema-label">Parameters:</div>
                              <div use:jsonView={tool.parameters}></div>
                            </div>
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/each}
          {:else}
            <div class="empty">None</div>
          {/if}
        </div>
      {:else if activeTab === 'settings'}
        <div class="settings">
          <h4>Settings</h4>
          <label><input type="checkbox" bind:checked={renderMarkdown}> Render assistant as Markdown</label>
          <div class="row">
            <button on:click={() => (lastError = null)} disabled={!lastError}>Clear error</button>
          </div>
        </div>
      {/if}
    </div>
  </aside>
</main>

<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  :global(body), :global(html), :global(#app) { height: 100%; width: 100%; margin: 0; }

  .shell {
    display: grid;
    grid-template-columns: 1fr 280px;
    height: 100vh;
    overflow: hidden;
    font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Noto Sans', 'Helvetica Neue', Arial, 'Apple Color Emoji', 'Segoe UI Emoji';
  }

  .chat { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }

  .error {
    margin: 0.5rem; padding: 0.5rem; background: #fee; color: #900; border: 1px solid #f99;
  }

  .messages {
    flex: 1 1 auto;
    min-height: 0;           /* allow internal scrolling */
    height: auto;            /* let flex sizing control height */
    overflow-y: auto;        /* vertical scroll */
    -webkit-overflow-scrolling: touch;
    scrollbar-gutter: stable both-edges; /* keep scrollbar space reserved */
    padding: 1rem;
    display: block;          /* avoid flex quirks that can suppress scroll */
  }
  .messages > .msg { margin-bottom: 0.5rem; }
  .empty { color: #666; }

  .msg { border-bottom: 1px solid #eee; padding-bottom: 0.5rem; }
  .kind { font-size: 0.75rem; color: #666; }
  .text { white-space: pre-wrap; }
  .text.md { white-space: normal; }
  .text.md :where(pre, code) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; }
  .pre { background: #f8f8f8; padding: 0.5rem; overflow: auto; max-height: 12rem; }

  /* End turn separator - thick horizontal rule */
  .end-turn-separator {
    height: 4px;
    background: #666;
    border: none;
    margin: 1rem 0;
    border-radius: 2px;
  }

  /* Terminal-style rendering */
  .terminal .terminal-body { background: #111; color: #eee; border-radius: 6px; padding: 0.5rem; max-height: 18rem; overflow: auto; }
  .terminal pre { margin: 0.25rem 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.85rem; line-height: 1.35; }
  .term-line { color: #9cdcfe; }
  .term-stdout { color: #d4d4d4; }
  .term-stderr { color: #f28b82; }
  .term-exit { color: #8ab4f8; font-size: 0.75rem; margin: 0.1rem 0 0.4rem; }
  .term-error { color: #ffb4ab; font-size: 0.75rem; margin: 0.2rem 0; }
  .term-approval { color: #ffd54f; font-size: 0.8rem; margin: 0.1rem 0; }
  .raw-toggle { margin-top: 0.5rem; }
  .raw-label { font-size: 0.75rem; color: #aaa; margin: 0.25rem 0; }

  .composer {
    display: flex; gap: 0.5rem; padding: 0.5rem; border-top: 1px solid #eee;
  }
  .composer textarea { flex: 1; resize: vertical; min-height: 2rem; }
  .composer button { white-space: nowrap; }

  .sidebar {
    border-left: 1px solid #eee;
    padding: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
  }

  /* Resize handle */
  .resize-handle {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    cursor: ew-resize;
    background: transparent;
    z-index: 10;
  }
  .resize-handle:hover {
    background: #007acc;
  }

  /* Sidebar header (connection status) */
  .sidebar-header {
    padding: 0.75rem;
    border-bottom: 1px solid #eee;
    flex-shrink: 0;
  }

  /* Tabs */
  .tabs {
    display: flex;
    border-bottom: 1px solid #eee;
    flex-shrink: 0;
  }
  .tab {
    flex: 1;
    padding: 0.5rem 0.25rem;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 0.75rem;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.25rem;
  }
  .tab:hover {
    background: rgba(0,0,0,0.05);
  }
  .tab.active {
    background: #f0f8ff;
    border-bottom: 2px solid #007acc;
  }
  .badge {
    background: #ff4444;
    color: white;
    font-size: 0.6rem;
    padding: 0.1rem 0.3rem;
    border-radius: 0.8rem;
    line-height: 1;
  }

  /* Tab content */
  .tab-content {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
  }

  /* Approvals tab specific styling */
  .approvals-tab {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  /* Policy Proposals */
  .proposals h4 { margin: 0.25rem 0; }
  .proposal {
    border: 1px solid #ddd;
    padding: 0.75rem;
    margin: 0.5rem 0;
    border-radius: 4px;
  }
  .proposal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  .proposal-status {
    font-size: 0.75rem;
    padding: 0.2rem 0.4rem;
    border-radius: 0.75rem;
    text-transform: uppercase;
    font-weight: 500;
  }
  .status-open {
    background: #e3f2fd;
    color: #1976d2;
  }
  .status-approved {
    background: #e8f5e8;
    color: #2e7d32;
  }
  .status-rejected {
    background: #ffebee;
    color: #c62828;
  }
  .status-withdrawn {
    background: #f5f5f5;
    color: #757575;
  }
  .proposal-rationale {
    color: #555;
    font-style: italic;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
  }
  .proposal-source {
    margin: 0.5rem 0;
  }
  .proposal-source summary {
    cursor: pointer;
    font-size: 0.85rem;
    color: #666;
    margin-bottom: 0.25rem;
  }
  .proposal-source summary:hover {
    color: #333;
  }
  .ws { display: flex; align-items: center; gap: 0.5rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #bbb; display: inline-block; }
  .dot.on { background: #2ecc71; }
  .dot.off { background: #bbb; }
  .status { color: #333; }
  .servers h4, .approvals h4 { margin: 0.25rem 0; }
  .server { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.85rem; }
  .approval { border: 1px solid #ddd; padding: 0.5rem; margin: 0.25rem 0; }
  .row { display: flex; gap: 0.5rem; flex-wrap: wrap; }

  /* Server and tool disclosure styles */
  .server-item { margin: 0.25rem 0; }
  .server-header, .tool-header {
    cursor: pointer;
    padding: 0.25rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    user-select: none;
  }
  .server-header:hover, .tool-header:hover { background: rgba(0,0,0,0.05); }
  .disclosure {
    font-size: 0.75rem;
    width: 1rem;
    flex-shrink: 0;
  }
  .server-name {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
    font-size: 0.85rem;
    font-weight: 500;
  }
  .tool-count {
    color: #666;
    font-size: 0.75rem;
    margin-left: auto;
  }
  .tools-list {
    margin-left: 1rem;
    border-left: 1px solid #e0e0e0;
    padding-left: 0.5rem;
  }
  .tool-item { margin: 0.25rem 0; }
  .tool-name {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
    font-size: 0.8rem;
  }
  .tool-details {
    margin-left: 1.5rem;
    margin-top: 0.25rem;
    padding: 0.5rem;
    background: rgba(0,0,0,0.02);
    border-radius: 0.25rem;
  }
  .tool-description {
    color: #555;
    font-size: 0.8rem;
    margin-bottom: 0.5rem;
  }
  .schema-label {
    font-weight: 500;
    font-size: 0.75rem;
    margin-bottom: 0.25rem;
    color: #666;
  }
  .tool-schema {
    font-size: 0.75rem;
  }
  .policy h4, .settings h4 { margin: 0.25rem 0; }
  .policy-content { background: #f8f8f8; padding: 0.5rem; overflow: auto; max-height: 12rem; font-size: 0.75rem; }
  .policy-editor { width: 100%; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.75rem; resize: vertical; }
</style>
