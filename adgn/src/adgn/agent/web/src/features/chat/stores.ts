/**
 * Main stores module - re-exports from modular channel stores.
 *
 * This module provides backward compatibility for existing components
 * while using the new modular WebSocket channel architecture internally.
 */

import { derived, type Readable } from 'svelte/store'

// Re-export all stores and functions from the modular channel implementation
export {
  type Pending,
  runStatus,
  uiStates,
  uiState,
  lastError,
  pendingApprovals,
  approvalPolicy,
  mcpServerEntries,
  clearError,
  sendPrompt,
  approve,
  denyContinue,
  deny,
  setPolicy,
  approveProposal,
  withdrawProposal,
  abortRun,
  reconfigureMcp,
} from './stores_channels'

import {
  channelsConnected,
  connectAgentChannels,
  disconnectAgentChannels,
} from './stores_channels'

// Backward compatibility: wsConnected as a derived store from channelsConnected
// Consider a connection "established" when at least one channel (typically MCP) is connected
export const wsConnected: Readable<boolean> = derived(
  channelsConnected,
  ($channels) => $channels.size > 0
)

// Backward compatibility: function name aliases
export const connectAgentWs = connectAgentChannels
export const disconnectAgentWs = disconnectAgentChannels

// Legacy refreshSnapshot is no longer needed - channels auto-push snapshots on connect
export async function refreshSnapshot() {
  // No-op: channels push snapshots automatically on connection
  // Old code that calls this for manual refresh can safely be removed
}
