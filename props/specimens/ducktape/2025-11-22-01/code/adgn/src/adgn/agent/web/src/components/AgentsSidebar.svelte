<script lang="ts">
  import { writable } from 'svelte/store'
  import { currentAgentId, setAgentId } from '../features/agents/stores'
  import { deleteAgent as apiDeleteAgent, listPresets, createAgentFromPreset } from '../features/agents/api'
  import { createMCPClient, readResource, subscribeToResource, type MCPClientConfig } from '../features/mcp/client'
  import { getOrExtractToken } from '../shared/token'
  import type { AgentInfo, AgentList } from '../generated/types'
  import { MCPUris } from '../generated/mcpConstants'
  import { prefs } from '../shared/prefs'
  import { LEFT_MIN, LEFT_MAX } from '../shared/layout'
  import SidebarToggle from './SidebarToggle.svelte'
  import ModalBackdrop from './ModalBackdrop.svelte'
  import type { Client } from '@modelcontextprotocol/sdk/client/index.js'
  import { ResourceUpdatedNotificationSchema } from '@modelcontextprotocol/sdk/types.js'

  export let onStartResize: (e: MouseEvent) => void

  // Local state for agents from MCP
  const agents = writable<AgentInfo[]>([])

  $: agentList = $agents
  $: selected = $currentAgentId
  let listEl: HTMLDivElement | null = null
  let presets: Array<{ name: string; description?: string | null }> = []
  let selectedPreset: string | null = null
  // Modal state for preset selection
  let showPresetModal = false
  let modalPreset: string | null = null
  let modalSystem: string = ''

  let mcpClient: Client | null = null
  let mcpError: string | null = null

  // Restore scroll position
  import { onMount, onDestroy } from 'svelte'
  async function refreshPresets() {
    try {
      const r = await listPresets()
      const list = r.presets || []
      presets = list
      if (showPresetModal) {
        if (!modalPreset || !list.find(p => p.name === modalPreset)) {
          modalPreset = list[0]?.name || null
        }
      }
    } catch {
      // ignore refresh failure
    }
  }
  async function fetchAgentsList() {
    if (!mcpClient) {
      console.warn('MCP client not connected, cannot fetch agents')
      return
    }
    try {
      const result = await readResource(mcpClient, MCPUris.agentsListUri)
      // result is an array of content items
      if (result && result.length > 0) {
        const content = result[0]
        if ('text' in content) {
          const data = JSON.parse(content.text) as AgentList
          agents.set(data.agents)
        }
      }
    } catch (err) {
      console.error('Failed to fetch agents list:', err)
      mcpError = err instanceof Error ? err.message : String(err)
    }
  }

  async function setupMCPClient() {
    const token = getOrExtractToken()
    if (!token) {
      mcpError = 'No authentication token found'
      console.error(mcpError)
      return
    }

    try {
      const config: MCPClientConfig = {
        name: 'agents-sidebar',
        url: `${window.location.protocol}//${window.location.host}/mcp`,
        token,
      }
      mcpClient = await createMCPClient(config)

      // Set up notification handler for resource updates
      mcpClient.setNotificationHandler(
        ResourceUpdatedNotificationSchema,
        async (notification) => {
          if (notification.params?.uri === MCPUris.agentsListUri) {
            await fetchAgentsList()
          }
        }
      )

      // Subscribe to agents list updates
      await subscribeToResource(mcpClient, MCPUris.agentsListUri)

      // Fetch initial list
      await fetchAgentsList()
    } catch (err) {
      console.error('Failed to setup MCP client:', err)
      mcpError = err instanceof Error ? err.message : String(err)
    }
  }

  onMount(() => {
    try {
      const saved = localStorage.getItem('agentsSidebarScrollTop')
      if (saved && listEl) listEl.scrollTop = parseInt(saved, 10) || 0
    } catch {}
    // Initial load
    refreshPresets()
    // Auto-refresh on focus and tab visibility
    const onFocus = () => { void refreshPresets() }
    const onVis = () => { if (document.visibilityState === 'visible') void refreshPresets() }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVis)

    // Setup MCP client for agents list
    void setupMCPClient()

    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVis)
      // Clean up MCP client
      if (mcpClient) {
        try {
          mcpClient.close()
        } catch {}
      }
    }
  })

  function open(id: string) {
    setAgentId(id)
  }

  // Inline delete confirm state
  let confirmingId: string | null = null

  async function openPresetDialog() {
    // Always refresh presets from backend so filesystem edits are reflected immediately
    try {
      const r = await listPresets()
      presets = r.presets || []
    } catch {
      // Keep prior list on fetch failure
    }
    if (!presets || presets.length === 0) {
      // No presets available; create default immediately
      try {
        const body = await createAgentFromPreset('default')
        const id = body?.id as string
        if (id) setAgentId(id)
      } catch (e) {
        console.warn('create default preset failed', e)
      }
      return
    }
    // Initialize modal selection after refresh
    modalPreset = selectedPreset || presets[0]?.name || null
    modalSystem = ''
    showPresetModal = true
  }

  async function confirmCreateFromModal() {
    if (!modalPreset) return
    try {
      const body = await createAgentFromPreset(modalPreset, modalSystem || undefined)
      const id = body?.id as string
      if (id) setAgentId(id)
    } catch (e) { console.warn('create agent from modal failed', e) }
    finally { showPresetModal = false }
  }

  async function createNewAgent() { // legacy path if modal not used
    openPresetDialog()
  }

  async function doDelete(id: string) {
    try {
      const body = await apiDeleteAgent(id)
      if (!body?.ok) throw new Error(body?.error || 'delete failed')
      // Optimistically update list and selection
      agents.update(list => (list || []).filter(a => a.agent_id !== id))
      if ($currentAgentId === id) setAgentId(null)
      confirmingId = null
    } catch (e) {
      console.warn('delete failed', e)
    }
  }

  async function createFromPreset() {
    if (!selectedPreset) return
    try {
      const body = await createAgentFromPreset(selectedPreset)
      const id = body?.id as string
      if (id) setAgentId(id)
    } catch (e) {
      console.warn('create from preset failed', e)
    }
  }

  function agentTitle(a: AgentInfo): string {
    const caps = Object.entries(a.capabilities)
      .filter(([_, enabled]) => enabled)
      .map(([cap]) => cap)
      .join(', ')
    return `Agent ${a.agent_id}\nMode: ${a.mode}\nCapabilities: ${caps || 'none'}`
  }

  function formatMode(mode: string): string {
    return mode.toUpperCase()
  }

  function getEnabledCapabilities(caps: Record<string, boolean>): string[] {
    return Object.entries(caps)
      .filter(([_, enabled]) => enabled)
      .map(([cap]) => cap)
  }
</script>

<aside class="leftbar" id="agents-sidebar">
  <div class="leftbar-header">
    <div class="row">
      <strong>Agents</strong>
      <button class="small add" title="Create new agent" aria-label="Create new agent" on:click={openPresetDialog}>+</button>
      <SidebarToggle
        title="Hide agents sidebar"
        label="Hide agents sidebar"
        glyph="«"
        action={() => prefs.update(p => ({ ...p, showAgentsSidebar: false }))}
      />
    </div>
    <!-- hint removed -->
  </div>
  <div class="agents-list" bind:this={listEl} on:scroll={() => {
    try { localStorage.setItem('agentsSidebarScrollTop', String(listEl?.scrollTop || 0)) } catch {}
  }}>
    {#if mcpError}
      <div class="error-message" role="alert">
        <strong>Error:</strong> {mcpError}
      </div>
    {/if}
    {#each agentList as a}
      <div
        class="agent-row {a.agent_id === selected ? 'current' : ''}"
        title={agentTitle(a)}
        aria-current={a.agent_id === selected ? 'true' : undefined}
        role="button"
        tabindex="0"
        on:click={() => open(a.agent_id)}
        on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(a.agent_id) } }}
      >
        <button type="button" class="agent-open" on:click={(e) => { e.stopPropagation(); open(a.agent_id) }}>
          <span class="agent-id">{a.agent_id.slice(0,8)}</span>
          <span class="badge mode mode-{a.mode}" title={`Mode: ${formatMode(a.mode)}`}>{formatMode(a.mode)}</span>
          {#each getEnabledCapabilities(a.capabilities) as cap}
            <span class="badge capability" title={`Capability: ${cap}`}>{cap}</span>
          {/each}
        </button>
        <div class="row-actions">
          {#if confirmingId === a.agent_id}
            <button class="danger small" on:click|stopPropagation={() => doDelete(a.agent_id)}>Confirm</button>
            <button class="secondary small" on:click|stopPropagation={() => (confirmingId = null)}>Cancel</button>
          {:else}
            <button class="danger small icon" aria-label="Delete agent" title="Delete agent" on:click|stopPropagation={() => (confirmingId = a.agent_id)}>×</button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
  <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
  <!-- svelte-ignore a11y-no-noninteractive-tabindex -->
  <div
    class="left-resize"
    role="separator"
    aria-orientation="vertical"
    aria-controls="agents-sidebar"
    aria-valuemin={LEFT_MIN}
    aria-valuemax={LEFT_MAX}
    aria-valuenow={$prefs.leftSidebarWidth}
    tabindex="0"
    on:mousedown={onStartResize}
    on:keydown={(e) => {
      const step = e.shiftKey ? 32 : 8
      if (e.key === 'ArrowLeft') { prefs.update(p => ({ ...p, leftSidebarWidth: Math.max(LEFT_MIN, p.leftSidebarWidth - step) })); e.preventDefault() }
      else if (e.key === 'ArrowRight') { prefs.update(p => ({ ...p, leftSidebarWidth: Math.min(LEFT_MAX, p.leftSidebarWidth + step) })); e.preventDefault() }
    }}
    title="Drag to resize"
    aria-label="Resize agents sidebar"
  ></div>
</aside>

{#if showPresetModal}
  <ModalBackdrop label="Close create agent dialog" onClose={() => (showPresetModal = false)}>
    <div class="modal" role="dialog" aria-modal="true" aria-label="Create agent from preset">
      <header>Create Agent</header>
      <div class="body">
        {#if presets.length > 0}
          <div class="row">
            <label for="modal-preset" style="min-width: 80px;">Preset</label>
            <select id="modal-preset" bind:value={modalPreset} style="flex: 1;">
              {#each presets as p}
                <option value={p.name}>{p.name}{p.description ? ` — ${p.description}` : ''}</option>
              {/each}
            </select>
          </div>
        {:else}
          <div>No presets found. This will use the built-in default.</div>
        {/if}
        <div class="row">
          <label for="modal-system" style="min-width: 80px;">System</label>
          <input id="modal-system" type="text" placeholder="(optional) override system message" bind:value={modalSystem} style="flex: 1;" />
        </div>
      </div>
      <footer>
        <button class="secondary" on:click={() => (showPresetModal = false)}>Cancel</button>
        <button class="primary" on:click={confirmCreateFromModal} disabled={!modalPreset && presets.length > 0}>Create</button>
      </footer>
    </div>
  </ModalBackdrop>
{/if}

<style>
  .leftbar { display: flex; flex-direction: column; position: relative; width: 100%; min-width: 0; }
  .leftbar-header { padding: 0.5rem; border-bottom: 1px solid var(--border); }
  .agents-list { overflow-y: auto; padding: 0.25rem 0.5rem; }
  .agent-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.25rem 0.25rem; border-radius: 4px; width: 100%; cursor: pointer; }
  .agent-row:hover { background: var(--surface-2); }
  .agent-row.current { background: rgba(25,118,210,0.1); }
  .agent-open { display: inline-flex; align-items: center; gap: 0.5rem; background: none; border: 1px solid transparent; cursor: pointer; padding: 0.2rem 0.25rem; flex-wrap: wrap; }
  .agent-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 0.85rem; }
  .badge { font-size: 0.65rem; padding: 0.05rem 0.3rem; border-radius: 0.5rem; text-transform: lowercase; border: 1px solid var(--border); white-space: nowrap; }
  .badge.mode { font-weight: 600; }
  .badge.mode.mode-local { background: rgba(46, 204, 113, 0.15); color: #2e7d32; border-color: rgba(46, 204, 113, 0.4); }
  .badge.mode.mode-bridge { background: rgba(33, 150, 243, 0.15); color: #1565c0; border-color: rgba(33, 150, 243, 0.4); }
  .badge.capability { background: rgba(255, 193, 7, 0.15); color: #b26a00; border-color: rgba(255, 193, 7, 0.4); }
  .error-message { padding: 0.5rem; background: rgba(176, 0, 32, 0.1); border: 1px solid rgba(176, 0, 32, 0.3); border-radius: 4px; color: #b00020; margin: 0.5rem; }
  /* Keep the resize handle within the sidebar to avoid overlaying the chat area */
  .left-resize { position: absolute; top: 0; right: 0; width: 6px; height: 100%; cursor: col-resize; background: transparent; border: none; padding: 0; }
  .row { display: flex; gap: 0.5rem; align-items: center; }
  .preset { flex: 1; min-width: 0; }
  /* Modal styles */
  /* Backdrop styling moved to ModalBackdrop component */
  .modal { background: var(--surface); color: var(--text); min-width: 320px; max-width: 90vw; border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.25); }
  .modal header { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); font-weight: 600; }
  .modal .body { padding: 0.75rem; display: grid; grid-template-columns: 1fr; gap: 0.5rem; }
  .modal .row { display: flex; gap: 0.5rem; align-items: center; }
  .modal footer { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 0.5rem 0.75rem; border-top: 1px solid var(--border); }
  .row :global(.toggle-btn) { margin-left: auto; }
  .row-actions { margin-left: auto; display: inline-flex; gap: 0.25rem; }
  .small { font-size: 0.75rem; padding: 0.2rem 0.4rem; }
  .danger { color: #b00020; }
  .secondary { background: var(--surface-2); }
  .icon { width: 22px; height: 22px; padding: 0; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; }
  .add { margin-left: auto; }
</style>
