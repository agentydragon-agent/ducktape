/**
 * MCP-based stores - uses MCP resource subscriptions instead of WebSocket channels
 *
 * Migrated from WebSocket /ws/session to MCP resource://agents/{id}/ui/state
 */

import { writable, derived, type Writable, type Readable } from 'svelte/store'
import { currentAgentId } from '../agents/stores'
import type { UiState } from '../../shared/types'
import { getMCPClient } from '../mcp/clientManager'
import { createSubscriptionManager } from '../mcp/subscriptions'
import { MCPUris } from '../../generated/mcpConstants'
import { readResource } from '../mcp/client'

const DEBUG = import.meta.env.DEV

// UI state per agent
export const uiStates: Writable<Map<string, UiState>> = writable(new Map())
export const uiState: Readable<UiState | null> = derived(
  [uiStates, currentAgentId],
  ([$uiStates, $current]) => ($current ? $uiStates.get($current) ?? null : null)
)

// Error state
export const lastError: Writable<string | null> = writable(null)

// Subscription manager instance (created on first subscription)
let subscriptionManager: Awaited<ReturnType<typeof createSubscriptionManager>> | null = null

/**
 * Subscribe to UI state updates for a specific agent
 */
export async function subscribeToAgentUiState(agentId: string): Promise<void> {
  try {
    // Initialize subscription manager if needed
    if (!subscriptionManager) {
      const client = await getMCPClient()
      subscriptionManager = createSubscriptionManager(client)
    }

    const uri = MCPUris.agentUiStateUri(agentId)

    if (DEBUG) console.log('[MCP] Subscribing to UI state:', uri)

    // Subscribe to resource updates
    await subscriptionManager.subscribe(uri, (data: any) => {
      if (DEBUG) console.log('[MCP] UI state update:', data)

      // Handle error responses
      if (data.error) {
        console.error('[MCP] UI state error:', data.message)
        lastError.set(data.message || 'Failed to load UI state')
        return
      }

      // Parse the resource contents
      try {
        // MCP resource returns array of content items
        if (Array.isArray(data) && data.length > 0) {
          const firstContent = data[0]
          if (firstContent.type === 'text' && firstContent.text) {
            const parsed = JSON.parse(firstContent.text)

            // The resource returns { seq, state: { seq, items } }
            // We want the inner state object
            const uiStateData: UiState = parsed.state || parsed

            // Update the store
            uiStates.update((map) => {
              const newMap = new Map(map)
              newMap.set(agentId, uiStateData)
              return newMap
            })

            // Clear any previous errors
            lastError.set(null)
          }
        }
      } catch (error) {
        console.error('[MCP] Failed to parse UI state:', error)
        lastError.set('Failed to parse UI state')
      }
    })

    if (DEBUG) console.log('[MCP] Subscribed to UI state:', uri)
  } catch (error) {
    console.error('[MCP] Failed to subscribe to UI state:', error)
    lastError.set(error instanceof Error ? error.message : 'Failed to subscribe to UI state')
    throw error
  }
}

/**
 * Unsubscribe from UI state updates for a specific agent
 */
export async function unsubscribeFromAgentUiState(agentId: string): Promise<void> {
  if (!subscriptionManager) return

  const uri = MCPUris.agentUiStateUri(agentId)
  if (DEBUG) console.log('[MCP] Unsubscribing from UI state:', uri)

  await subscriptionManager.unsubscribe(uri)
}

/**
 * Clear error state
 */
export function clearError() {
  lastError.set(null)
}

/**
 * Cleanup all subscriptions
 */
export async function cleanup() {
  if (subscriptionManager) {
    await subscriptionManager.cleanup()
    subscriptionManager = null
  }
  uiStates.set(new Map())
  lastError.set(null)
}
