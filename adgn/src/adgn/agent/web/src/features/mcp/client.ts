/**
 * MCP Client wrapper for agent web UI.
 *
 * Provides simplified interface for connecting to the MCP compositor and calling tools/resources.
 * Supports bearer token authentication from URL query param (?token=...).
 */
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'

export interface McpClientOptions {
  /** Agent ID for scoping tool calls (used as prefix in compositor hierarchy) */
  agentId?: string
  /** Bearer token for authentication (defaults to URL query param) */
  token?: string
}

/**
 * Get authentication token from URL query params or localStorage.
 */
function getAuthToken(): string | null {
  // Check URL query param first
  const params = new URLSearchParams(window.location.search)
  const urlToken = params.get('token')
  if (urlToken) {
    // Store in localStorage for persistence across page reloads
    localStorage.setItem('adgn_auth_token', urlToken)
    return urlToken
  }
  // Fall back to localStorage
  return localStorage.getItem('adgn_auth_token')
}

export class AgentMcpClient {
  private client: Client
  private transport: StreamableHTTPClientTransport
  private agentId?: string

  private constructor(client: Client, transport: StreamableHTTPClientTransport, agentId?: string) {
    this.client = client
    this.transport = transport
    this.agentId = agentId
  }

  /**
   * Connect to the global MCP compositor endpoint.
   *
   * The compositor exposes tools from all agents via nested sub-compositors.
   * Use agentId option to automatically prefix tool calls for a specific agent.
   *
   * @param options - Optional agent ID for automatic tool name prefixing
   * @returns Connected MCP client instance
   */
  static async connect(options: McpClientOptions = {}): Promise<AgentMcpClient> {
    const url = `${window.location.origin}/mcp`

    // Get auth token
    const token = options.token ?? getAuthToken()
    if (!token) {
      throw new Error('No authentication token found. Add ?token=... to URL.')
    }

    // Create transport with bearer token auth
    const transport = new StreamableHTTPClientTransport(new URL(url), {
      requestInit: {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      },
    })

    const client = new Client(
      { name: 'adgn-web', version: '1.0.0' },
      // @ts-expect-error - SDK types don't expose resources capability but it's needed
      { capabilities: { resources: { subscribe: true } } }
    )

    await client.connect(transport)
    return new AgentMcpClient(client, transport, options.agentId)
  }

  /**
   * Call an MCP tool.
   *
   * Tool names are automatically prefixed with agent ID if configured.
   * Example: 'approve_call' becomes '{agentId}_approve_call'
   *
   * FastMCP compositor prefixes tools as: {server}_{tool}
   *
   * @param name - Tool name (without agent prefix)
   * @param args - Tool arguments
   * @returns Tool result (parsed from first content item)
   */
  async callTool<T = unknown>(name: string, args: Record<string, unknown> = {}): Promise<T> {
    const toolName = this.agentId ? `${this.agentId}_${name}` : name
    const result = await this.client.callTool({ name: toolName, arguments: args })
    // Cast to expected shape - MCP SDK types don't fully describe the result
    const content = result.content as Array<{ type: string; text?: string }> | undefined
    if (content && content.length > 0) {
      const first = content[0]
      if (first.type === 'text' && first.text) {
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
   * Resource URIs are automatically prefixed with agent ID if configured.
   * FastMCP default resource_prefix_format is "path", which transforms:
   *   approvals://pending → approvals://agent123/pending
   *
   * @param uri - Resource URI (without agent prefix)
   * @returns Resource contents (parsed from first content item)
   */
  async readResource<T = unknown>(uri: string): Promise<T> {
    // FastMCP "path" format: protocol://prefix/path
    const resourceUri = this.agentId ? this.prefixResourceUri(uri, this.agentId) : uri
    const result = await this.client.readResource({ uri: resourceUri })
    // Cast to expected shape - MCP SDK union type doesn't narrow well
    const contents = result.contents as Array<{ uri: string; mimeType?: string; text?: string }> | undefined
    if (contents && contents.length > 0) {
      const first = contents[0]
      if (first.text !== undefined) {
        if (first.mimeType === 'application/json' || first.uri.startsWith('approvals://')) {
          return JSON.parse(first.text) as T
        }
        return first.text as T
      }
    }
    throw new Error(`No content in resource: ${uri}`)
  }

  /**
   * Subscribe to an MCP resource and poll for updates.
   *
   * Resource URIs are automatically prefixed with agent ID if configured.
   * FastMCP default resource_prefix_format is "path", which transforms:
   *   approvals://pending → approvals://agent123/pending
   *
   * Note: This implementation uses polling since MCP notifications aren't reliably
   * delivered in all transport modes. The callback will be invoked whenever the
   * resource content changes.
   *
   * @param uri - Resource URI to subscribe to (without agent prefix)
   * @param callback - Called with resource data on updates
   * @param pollIntervalMs - Polling interval (default: 1000ms)
   * @returns Unsubscribe function
   */
  async subscribeResource<T>(
    uri: string,
    callback: (data: T) => void,
    pollIntervalMs: number = 1000
  ): Promise<() => void> {
    // FastMCP "path" format: protocol://prefix/path
    const resourceUri = this.agentId ? this.prefixResourceUri(uri, this.agentId) : uri
    await this.client.subscribeResource({ uri: resourceUri })

    let active = true
    let lastContent: string | null = null

    const poll = async () => {
      while (active) {
        try {
          const result = await this.client.readResource({ uri: resourceUri })
          // Cast to expected shape - MCP SDK union type doesn't narrow well
          const contents = result.contents as Array<{ uri: string; mimeType?: string; text?: string }> | undefined
          if (contents && contents.length > 0) {
            const first = contents[0]
            const content = first.text
            // Only call callback if content changed
            if (content !== undefined && content !== lastContent) {
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
      // Unsubscribe from resource (use same prefixed URI)
      this.client.unsubscribeResource({ uri: resourceUri }).catch(e => {
        console.warn(`Failed to unsubscribe from ${resourceUri}:`, e)
      })
    }
  }

  /**
   * Apply FastMCP "path" format resource prefix.
   * Transforms: protocol://path → protocol://prefix/path
   *
   * @param uri - Original resource URI
   * @param prefix - Prefix to add (agent ID)
   * @returns Prefixed resource URI
   */
  private prefixResourceUri(uri: string, prefix: string): string {
    const match = uri.match(/^([^:]+:\/\/)(.*)$/)
    if (!match) {
      throw new Error(`Invalid resource URI format: ${uri}`)
    }
    const [, protocol, path] = match
    return `${protocol}${prefix}/${path}`
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
