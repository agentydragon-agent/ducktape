/**
 * MCP Manager - Manages MCP client connections and provides connection status.
 *
 * Singleton instance that handles per-agent MCP client connections.
 */
import { writable, type Writable } from 'svelte/store'
import { AgentMcpClient } from './client'

export interface ConnectionStatus {
  connected: boolean
  error: string | null
}

class McpManager {
  // Per-agent clients
  private agentClients = new Map<string, AgentMcpClient>()

  // Connection status store
  public connectionStatus: Writable<ConnectionStatus> = writable({
    connected: false,
    error: null,
  })

  /**
   * Connect to a specific agent's MCP compositor.
   *
   * @param agentId - Agent ID to connect to
   * @returns Connected MCP client for the agent
   */
  async connectAgent(agentId: string): Promise<AgentMcpClient> {
    const existing = this.agentClients.get(agentId)
    if (existing) return existing

    try {
      const client = await AgentMcpClient.connect({ agentId })
      this.agentClients.set(agentId, client)
      this.connectionStatus.set({ connected: true, error: null })
      return client
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e)
      this.connectionStatus.set({ connected: false, error })
      throw e
    }
  }

  /**
   * Get existing client for agent (returns null if not connected).
   *
   * @param agentId - Agent ID
   * @returns MCP client or null if not connected
   */
  getClient(agentId: string): AgentMcpClient | null {
    return this.agentClients.get(agentId) ?? null
  }

  /**
   * Disconnect from an agent's MCP compositor.
   *
   * @param agentId - Agent ID to disconnect
   */
  async disconnectAgent(agentId: string): Promise<void> {
    const client = this.agentClients.get(agentId)
    if (client) {
      await client.close()
      this.agentClients.delete(agentId)
      // Update status if no more clients connected
      if (this.agentClients.size === 0) {
        this.connectionStatus.set({ connected: false, error: null })
      }
    }
  }

  /**
   * Disconnect all clients.
   */
  async disconnectAll(): Promise<void> {
    const clients = Array.from(this.agentClients.values())
    this.agentClients.clear()
    await Promise.all(clients.map(c => c.close().catch(e => console.warn('Close error:', e))))
    this.connectionStatus.set({ connected: false, error: null })
  }
}

// Singleton instance
export const mcpManager = new McpManager()
