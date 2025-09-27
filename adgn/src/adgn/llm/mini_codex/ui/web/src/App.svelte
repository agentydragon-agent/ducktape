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
  let lastError: string | null = null
  let messagesEl: HTMLDivElement | null = null
  let promptEl: HTMLTextAreaElement | null = null
  let renderMarkdown = true
  let uiState: any = null

  // Persist settings reactively
  $: try { localStorage.setItem('renderMarkdown', JSON.stringify(renderMarkdown)) } catch {}


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

<main class="shell">
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
                  {#if it.content.output}
                    <details open>
                      <summary>Output</summary>
                      <div use:jsonView={it.content.output}></div>
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
    <div class="ws">
      <span class="dot {connected ? 'on' : 'off'}"></span>
      <span>{connected ? 'connected' : 'disconnected'}</span>
    </div>
    <div class="status">Status: {status}</div>
    <div class="servers">
      <h4>Servers</h4>
      {#if mcpServers.length}
        {#each mcpServers as n}
          <div class="server">{n}</div>
        {/each}
      {:else}
        <div class="empty">None</div>
      {/if}
    </div>

    <div class="settings">
      <h4>Settings</h4>
      <label><input type="checkbox" bind:checked={renderMarkdown}> Render assistant as Markdown</label>
      <div class="row">
        <button on:click={() => (lastError = null)} disabled={!lastError}>Clear error</button>
      </div>
    </div>

    <div class="approvals">
      <h4>Pending approvals ({pending.size})</h4>
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

  /* Terminal-style rendering */
  .terminal .terminal-body { background: #111; color: #eee; border-radius: 6px; padding: 0.5rem; max-height: 18rem; overflow: auto; }
  .terminal pre { margin: 0.25rem 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.85rem; line-height: 1.35; }
  .term-line { color: #9cdcfe; }
  .term-stdout { color: #d4d4d4; }
  .term-stderr { color: #f28b82; }
  .term-exit { color: #8ab4f8; font-size: 0.75rem; margin: 0.1rem 0 0.4rem; }
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
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    overflow-y: auto;
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
</style>
