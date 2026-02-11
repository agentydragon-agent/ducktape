<script lang="ts">
  import { createMCPClient, callTool, MCPClientError } from '../features/mcp/client'
  import { getOrExtractToken } from '../shared/token'
  import { backendOrigin } from '../features/agents/api'

  // Props
  export let agentId: string
  export let onAbortAgent: () => void

  // Local state
  let message = ''
  let sending = false
  let error: string | null = null

  // Send message to agent via MCP prompt tool
  async function sendMessage() {
    if (!message.trim() || !agentId || sending) return

    sending = true
    error = null

    try {
      const token = getOrExtractToken()
      if (!token) {
        throw new Error('Authentication required')
      }

      const client = await createMCPClient({
        name: 'message-composer-client',
        url: `${backendOrigin()}/mcp`,
        token
      })

      await callTool(client, 'prompt', { agent_id: agentId, message: message })

      // Clear message on success
      message = ''
    } catch (e) {
      if (e instanceof MCPClientError) {
        error = e.message
      } else {
        error = e instanceof Error ? e.message : String(e)
      }
    } finally {
      sending = false
    }
  }

  // Handle Enter key (Shift+Enter for new line, Enter for send)
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }
</script>

<div class="message-composer">
  <div class="composer-header">
    <h4>Message Composer</h4>
    {#if error}
      <div class="error">{error}</div>
    {/if}
  </div>

  <div class="composer-body">
    <textarea
      bind:value={message}
      on:keydown={handleKeydown}
      placeholder="Type a message... (Enter to send, Shift+Enter for new line)"
      class="message-input"
      disabled={sending}
      rows="3"
    ></textarea>

    <div class="composer-actions">
      <button
        on:click={sendMessage}
        disabled={!message.trim() || sending}
        class="send-btn"
      >
        {sending ? 'Sending...' : 'Send'}
      </button>
      <button
        on:click={onAbortAgent}
        class="abort-btn"
        disabled={sending}
      >
        Abort Agent
      </button>
    </div>
  </div>
</div>

<style>
  .message-composer {
    border-top: 1px solid var(--border);
    background: var(--surface);
    display: flex;
    flex-direction: column;
    min-height: 120px;
  }

  .composer-header {
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  h4 {
    margin: 0;
    font-size: 0.9rem;
    color: var(--text);
  }

  .error {
    color: #b00020;
    font-size: 0.8rem;
  }

  .composer-body {
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
  }

  .message-input {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    color: var(--text);
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 0.9rem;
    resize: vertical;
    min-height: 60px;
  }

  .message-input:focus {
    outline: none;
    border-color: #2ecc71;
  }

  .message-input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .composer-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }

  button {
    padding: 0.4rem 1rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-2);
    color: var(--text);
    cursor: pointer;
    font-size: 0.9rem;
  }

  button:hover:not(:disabled) {
    background: var(--surface-3);
  }

  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .send-btn {
    background: #2ecc71;
    color: white;
    border-color: #27ae60;
  }

  .send-btn:hover:not(:disabled) {
    background: #27ae60;
  }

  .abort-btn {
    background: #e74c3c;
    color: white;
    border-color: #c0392b;
  }

  .abort-btn:hover:not(:disabled) {
    background: #c0392b;
  }
</style>
