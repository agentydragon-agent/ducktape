<script lang="ts">
  import ApprovalsPanel from './ApprovalsPanel.svelte'
  import ServersPanel from './ServersPanel.svelte'
  import SettingsPanel from './SettingsPanel.svelte'
  
  import { agentStatus as agentStatusStore, agentStatusError as agentStatusErrorStore } from '../features/agents/stores'
  import { wsConnected, runStatus as runStatusStore, pendingApprovals, approvalPolicy as approvalPolicyStore, mcpServerEntries as mcpServerEntriesStore, lastError as lastErrorStore, clearError as clearWsError, approve as wsApprove, denyContinue as wsDenyContinue, deny as wsDeny, setPolicy as wsSetPolicy, applyProposal as wsApplyProposal } from '../features/chat/stores'

  // Local UI state
  let activeTab: 'approvals' | 'servers' | 'settings' = 'approvals'
  let showPolicyEditor = false
  let editingPolicy = ''

  export let deleteCurrentAgent: () => void

  
  function startEditingPolicy() { editingPolicy = ($approvalPolicyStore?.content) || ''; showPolicyEditor = true }
  function cancelEditingPolicy() { showPolicyEditor = false; editingPolicy = '' }
</script>

<div class="sidebar-header">
  <div class="ws" title={$wsConnected ? 'WebSocket connected (browser ↔ server). Controls live updates; not agent liveness.' : 'WebSocket disconnected (browser ↔ server). Live updates paused; not agent liveness.'}>
    <span class="dot {$wsConnected ? 'on' : 'off'}"></span>
    <span>{$wsConnected ? 'WS connected' : 'WS disconnected'}</span>
  </div>
  <div class="status">Status: {$runStatusStore}</div>
  {#if $agentStatusErrorStore}
    <div class="status-error" title={$agentStatusErrorStore}>
      Agent status unavailable
    </div>
  {/if}
  <!-- Left sidebar toggle moved out of right sidebar -->
  <!-- Agent selection moved to left sidebar (AgentsSidebar). -->
</div>

<div class="tabs">
  <button class="tab {activeTab === 'approvals' ? 'active' : ''}" on:click={() => (activeTab = 'approvals')}>
    Approvals{#if Array.from($pendingApprovals.values()).length > 0} <span class="badge">{Array.from($pendingApprovals.values()).length}</span>{/if}
  </button>
  <button class="tab {activeTab === 'servers' ? 'active' : ''}" on:click={() => (activeTab = 'servers')}>
    MCP ({$mcpServerEntriesStore.length})
  </button>
  <button class="tab {activeTab === 'settings' ? 'active' : ''}" on:click={() => (activeTab = 'settings')}>
    Settings
  </button>
</div>

<div class="tab-content">
  {#if activeTab === 'approvals'}
    <ApprovalsPanel
      approvalPolicy={$approvalPolicyStore}
      {showPolicyEditor}
      {editingPolicy}
      {startEditingPolicy}
      {cancelEditingPolicy}
      setPolicy={wsSetPolicy}
      approveProposal={(id) => wsApplyProposal(id, 'approve')}
      rejectProposal={(id) => wsApplyProposal(id, 'reject')}
      approve={wsApprove}
      denyContinue={wsDenyContinue}
      deny={wsDeny}
      pending={Array.from($pendingApprovals.values())}
    />
  {:else if activeTab === 'servers'}
    <ServersPanel servers={$mcpServerEntriesStore} />
  {:else}
    <SettingsPanel
      lastError={$lastErrorStore}
      clearError={() => clearWsError()}
      {deleteCurrentAgent}
    />
  {/if}
</div>

<style>
  :global(#right-sidebar) { display: flex; flex-direction: column; overflow: hidden; }
  .sidebar-header { padding: 0.5rem; border-bottom: 1px solid var(--border); }
  .ws { display: flex; align-items: center; gap: 0.5rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #bbb; display: inline-block; }
  .dot.on { background: #2ecc71; }
  .dot.off { background: #bbb; }
  .status { color: var(--text); }
  .status-error { color: #b00020; font-size: 0.75rem; margin-top: 0.25rem; }
  .agent-badge { display: inline-flex; align-items: center; gap: 0.25rem; }
  .agent-dot { width: 10px; height: 10px; border-radius: 50%; background: #bbb; display: inline-block; }
  .agent-dot.on { background: #2ecc71; }
  .agent-dot.off { background: #bbb; }
  .badge { background: var(--surface-3); border-radius: 0.75rem; padding: 0 0.4rem; font-size: 0.7rem; }
  .row { display: flex; gap: 0.5rem; align-items: center; }
  .tabs { display: flex; gap: 0.25rem; padding: 0.5rem; border-bottom: 1px solid var(--border); }
  .tab { padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-bottom: none; background: var(--surface-2); color: var(--text); cursor: pointer; }
  .tab.active { background: var(--surface); font-weight: 600; }
  .tab-content { padding: 0.5rem; flex: 1 1 auto; min-height: 0; overflow-y: auto; }
  .small { font-size: 0.75rem; padding: 0.2rem 0.4rem; }
</style>
