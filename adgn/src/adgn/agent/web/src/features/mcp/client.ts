/**
 * MCP Client wrapper for agent web UI.
 *
 * Provides simplified interface for connecting to the MCP compositor and calling tools/resources.
 */
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js'

export interface McpClientOptions {
  agentId?: string
}

export class AgentMcpClient {
  private client: Client
  private transport: SSEClientTransport

  private constructor(client: Client, transport: SSEClientTransport) {
    this.client = client
    this.transport = transport
  }

  /**
   * Connect to the MCP compositor endpoint.
   *
   * @param options - Optional agent ID to connect to a specific agent's compositor
   * @returns Connected MCP client instance
   */
  static async connect(options: McpClientOptions = {}): Promise<AgentMcpClient> {
    const url = options.agentId
      ? `${window.location.origin}/mcp?agent_id=${options.agentId}`
      : `${window.location.origin}/mcp`

    const transport = new SSEClientTransport(new URL(url))
    const client = new Client(
      { name: 'adgn-web', version: '1.0.0' },
      { capabilities: { resources: { subscribe: true } } }
    )

    await client.connect(transport)
    return new AgentMcpClient(client, transport)
  }

  /**
   * Call an MCP tool.
   *
   * @param name - Tool name (e.g., 'approvals_approve_call')
   * @param args - Tool arguments
   * @returns Tool result (parsed from first content item)
   */
  async callTool<T = unknown>(name: string, args: Record<string, unknown> = {}): Promise<T> {
    const result = await this.client.callTool({ name, arguments: args })
    if (result.content && result.content.length > 0) {
      const first = result.content[0]
      if (first.type === 'text') {
        try {
          return JSON.parse(first.text) as T
        } catch {
          return first.text as T
        }
      }
    }
    return result as T
  }

  /**
   * Read an MCP resource.
   *
   * @param uri - Resource URI (e.g., 'approvals://pending')
   * @returns Resource contents (parsed from first content item)
   */
  async readResource<T = unknown>(uri: string): Promise<T> {
    const result = await this.client.readResource({ uri })
    if (result.contents && result.contents.length > 0) {
      const first = result.contents[0]
      if (first.mimeType === 'application/json' || first.uri.startsWith('approvals://')) {
        return JSON.parse(first.text) as T
      }
      return first.text as T
    }
    throw new Error(`No content in resource: ${uri}`)
  }

  /**
   * Subscribe to an MCP resource and poll for updates.
   *
   * Note: This implementation uses polling since MCP notifications aren't reliably
   * delivered in all transport modes. The callback will be invoked whenever the
   * resource content changes.
   *
   * @param uri - Resource URI to subscribe to
   * @param callback - Called with resource data on updates
   * @param pollIntervalMs - Polling interval (default: 1000ms)
   * @returns Unsubscribe function
   */
  async subscribeResource<T>(
    uri: string,
    callback: (data: T) => void,
    pollIntervalMs: number = 1000
  ): Promise<() => void> {
    await this.client.subscribeResource({ uri })

    let active = true
    let lastContent: string | null = null

    const poll = async () => {
      while (active) {
        try {
          const result = await this.client.readResource({ uri })
          if (result.contents && result.contents.length > 0) {
            const first = result.contents[0]
            const content = first.text
            // Only call callback if content changed
            if (content !== lastContent) {
              lastContent = content
              const data = first.mimeType === 'application/json' || uri.startsWith('approvals://')
                ? JSON.parse(content) as T
                : content as T
              callback(data)
            }
          }
        } catch (e) {
          console.error(`Resource subscription error: ${uri}`, e)
        }
        await new Promise(r => setTimeout(r, pollIntervalMs))
      }
    }

    poll()
    return () => {
      active = false
      // Unsubscribe from resource
      this.client.unsubscribeResource({ uri }).catch(e => {
        console.warn(`Failed to unsubscribe from ${uri}:`, e)
      })
    }
  }

  /**
   * List available tools.
   *
   * @returns List of available MCP tools
   */
  async listTools() {
    return await this.client.listTools()
  }

  /**
   * List available resources.
   *
   * @returns List of available MCP resources
   */
  async listResources() {
    return await this.client.listResources()
  }

  /**
   * Close the MCP client connection.
   */
  async close(): Promise<void> {
    await this.client.close()
  }
}
