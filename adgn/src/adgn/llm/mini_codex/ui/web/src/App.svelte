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
    ws.onclose = () => {
      connected = false
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
        transcript = [...transcript, { type: 'approval_decision', call_id: p.call_id, decision: p.decision?.kind }]
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

  onMount(() => {
    connect()
  })
</script>

<main>
  <header style="display:flex; gap:1rem; align-items:baseline; flex-wrap:wrap;">
    <strong>MiniCodex</strong>
    <span>WS: {connected ? 'connected' : 'disconnected'}</span>
    <span>Status: {status}</span>
    {#if mcpServers.length}
      <span>Servers: {mcpServers.join(', ')}</span>
    {/if}
  </header>

  {#if lastError}
    <div style="margin-top:0.5rem; padding:0.5rem; background:#fee; color:#900; border:1px solid #f99;">
      Error: {lastError}
    </div>
  {/if}

  <section style="margin-top:1rem;">
    <form on:submit|preventDefault={sendPrompt} style="display:flex; gap:0.5rem;">
      <input bind:value={prompt} placeholder="Type a prompt…" style="flex:1; padding:0.5rem;" />
      <button type="submit" disabled={!connected}>Send</button>
    </form>
  </section>

  <section style="margin-top:1rem;">
    <h3>Pending approvals ({pending.size})</h3>
    {#if pending.size === 0}
      <div style="color:#666;">None</div>
    {:else}
      {#each Array.from(pending.values()) as p}
        <div style="border:1px solid #ddd; padding:0.5rem; margin:0.5rem 0;">
          <div><code>{p.tool_key}</code> <small>({p.call_id})</small></div>
          {#if p.args_json}
            <pre style="background:#f8f8f8; padding:0.5rem; overflow:auto; max-height:12rem;">{prettyArgs(p.args_json)}</pre>
          {/if}
          <div style="display:flex; gap:0.5rem;">
            <button on:click={() => approve(p.call_id)}>Approve</button>
            <button on:click={() => denyContinue(p.call_id)}>Deny (continue)</button>
            <button on:click={() => deny(p.call_id)}>Deny (abort)</button>
          </div>
        </div>
      {/each}
    {/if}
  </section>

  <section style="margin-top:1rem;">
    <h3>Transcript</h3>
    {#if transcript.length === 0}
      <div style="color:#666;">No messages yet.</div>
    {:else}
      <div style="display:flex; flex-direction:column; gap:0.5rem;">
        {#each transcript as item}
          <div style="border-bottom:1px solid #eee; padding-bottom:0.5rem;">
            <code>{item.type}</code>
            {#if item.type === 'assistant_text' || item.type === 'user_text'}
              <div style="white-space:pre-wrap;">{item.text}</div>
            {:else if item.type === 'tool_call'}
              <div><strong>{item.name}</strong></div>
              {#if item.args_json}<pre style="background:#f8f8f8; padding:0.5rem; overflow:auto;">{prettyArgs(item.args_json)}</pre>{/if}
            {:else if item.type === 'function_call_output'}
              <pre style="background:#f8f8f8; padding:0.5rem; overflow:auto;">{prettyArgs(item.output)}</pre>
            {:else if item.type === 'approval_decision'}
              <div>Decision: {item.decision}</div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </section>
</main>

<style>
  main {
    max-width: 900px;
    margin: 1rem auto;
    padding: 0 1rem;
    font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Noto Sans', 'Helvetica Neue', Arial, 'Apple Color Emoji', 'Segoe UI Emoji';
  }
  input, button {
    font: inherit;
  }
</style>
