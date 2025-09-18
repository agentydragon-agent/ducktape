<script lang="ts">
  import { onMount } from 'svelte'

  type Pending = { call_id: string; tool_key: string; args_json?: string | null }

  let ws: WebSocket | null = null
  let connected = false
  let status: string = 'idle'
  let prompt = ''
  let pending = new Map<string, Pending>()
  let transcript: any[] = []
  let mcpServers: string[] = []
  let lastError: string | null = null
  let messagesEl: HTMLDivElement | null = null

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws`)
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
        if (Array.isArray(p.transcript)) {
          transcript = p.transcript
          requestAnimationFrame(() => { if (stickToBottom) scrollToBottom() })
        }
        if (p.run_state?.status) status = p.run_state.status
        break
      case 'run_status':
        status = p.run_state?.status || status
        break
      case 'user_text':
      case 'assistant_text':
      case 'tool_call':
      case 'function_call_output':
      case 'reasoning':
        transcript = [...transcript, p]
        requestAnimationFrame(() => { if (stickToBottom) scrollToBottom() })
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
        transcript = [
          ...transcript,
          { type: 'approval_decision', call_id: p.call_id, decision: p.decision?.kind }
        ]
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
  })
</script>

<main class="shell">
  <section class="chat">
    {#if lastError}
      <div class="error">Error: {lastError}</div>
    {/if}

    <div class="messages" bind:this={messagesEl} on:scroll={onMessagesScroll}>
      {#if transcript.length === 0}
        <div class="empty">No messages yet.</div>
      {:else}
        {#each transcript as item}
          <div class="msg">
            <div class="kind">{item.type}</div>
            {#if item.type === 'assistant_text' || item.type === 'user_text'}
              <div class="text">{item.text}</div>
            {:else if item.type === 'tool_call'}
              <div class="tool">
                <strong>{item.name}</strong>
                {#if item.args_json}
                  <pre class="pre">{prettyArgs(item.args_json)}</pre>
                {/if}
              </div>
            {:else if item.type === 'function_call_output'}
              <pre class="pre">{prettyArgs(item.output)}</pre>
            {:else if item.type === 'approval_decision'}
              <div>Decision: {item.decision}</div>
            {/if}
          </div>
        {/each}
      {/if}
    </div>

    <form class="composer" on:submit|preventDefault={sendPrompt}>
      <textarea bind:value={prompt} rows="3" placeholder="Type a prompt…" />
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
  body, html, #app { height: 100%; width: 100%; margin: 0; }

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
  .pre { background: #f8f8f8; padding: 0.5rem; overflow: auto; max-height: 12rem; }

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
