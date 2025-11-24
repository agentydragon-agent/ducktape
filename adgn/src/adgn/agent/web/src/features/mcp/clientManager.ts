/**
 * MCP Client Manager for Frontend
 *
 * Manages the MCP client connection to the agents server at /mcp/agents.
 * Provides a singleton client instance with automatic initialization.
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { createMCPClient, MCPClientError, type MCPClientConfig } from './client'

let clientInstance: Client | null = null
let clientPromise: Promise<Client> | null = null

/**
 * Get UI token from URL parameters or environment
 */
function getUIToken(): string {
  // Try URL parameter first (for bridge mode)
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')
  if (token) return token

  // Try environment variable (for local mode)
  const envToken = import.meta.env.VITE_UI_TOKEN
  if (envToken) return envToken

  // For development without a token, use a placeholder
  // (the backend may be running without authentication)
  console.warn('No UI token found in URL or environment, using empty token')
  return ''
}

/**
 * Get MCP server URL relative to current origin
 */
function getMCPServerURL(): string {
  const origin = window.location.origin
  return `${origin}/mcp/agents/sse`
}

/**
 * Initialize the MCP client (called once on app startup)
 *
 * @returns Promise that resolves to the connected client
 * @throws MCPClientError if connection fails
 */
export async function initMCPClient(): Promise<Client> {
  if (clientInstance) {
    return clientInstance
  }

  if (clientPromise) {
    return clientPromise
  }

  clientPromise = (async () => {
    try {
      const config: MCPClientConfig = {
        name: 'agents-ui',
        url: getMCPServerURL(),
        token: getUIToken()
      }

      const client = await createMCPClient(config)
      clientInstance = client
      return client
    } catch (error) {
      clientPromise = null // Reset on error so retry is possible
      throw error
    }
  })()

  return clientPromise
}

/**
 * Get the initialized MCP client
 *
 * Automatically initializes the client on first call.
 *
 * @returns Promise that resolves to the connected client
 * @throws MCPClientError if client cannot be initialized
 */
export async function getMCPClient(): Promise<Client> {
  return initMCPClient()
}

/**
 * Disconnect the MCP client (cleanup)
 */
export async function disconnectMCPClient(): Promise<void> {
  if (clientInstance) {
    try {
      await clientInstance.close()
    } catch (error) {
      console.error('Error closing MCP client:', error)
    }
    clientInstance = null
    clientPromise = null
  }
}
