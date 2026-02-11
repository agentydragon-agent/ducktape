import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

/**
 * Configuration for creating an MCP client
 */
export interface MCPClientConfig {
  /** Client name identifier */
  name: string;
  /** Server URL to connect to */
  url: string;
  /** Bearer token for authorization */
  token: string;
}

/**
 * Error thrown when MCP client operations fail
 */
export class MCPClientError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'MCPClientError';
  }
}

/**
 * Create and connect an MCP client with StreamableHTTP transport
 *
 * @param config - Client configuration including name, URL, and auth token
 * @returns Promise resolving to connected Client instance
 * @throws MCPClientError if connection fails
 */
export async function createMCPClient(config: MCPClientConfig): Promise<Client> {
  try {
    // Create client with name and version
    const client = new Client(
      {
        name: config.name,
        version: '1.0.0',
      },
      {
        capabilities: {},
      }
    );

    // Create transport with URL and authorization header
    const url = new URL(config.url);
    const transport = new StreamableHTTPClientTransport(url, {
      requestInit: {
        headers: {
          Authorization: `Bearer ${config.token}`,
        },
      },
    });

    // Connect to the server
    await client.connect(transport);

    return client;
  } catch (error) {
    throw new MCPClientError(
      `Failed to create MCP client: ${error instanceof Error ? error.message : String(error)}`,
      error
    );
  }
}

/**
 * Read a resource from an MCP server
 *
 * @param client - Connected MCP client
 * @param uri - Resource URI to read
 * @returns Promise resolving to resource contents
 * @throws MCPClientError if read fails
 */
export async function readResource(client: Client, uri: string): Promise<any> {
  try {
    const result = await client.readResource({ uri });
    return result.contents;
  } catch (error) {
    throw new MCPClientError(
      `Failed to read resource ${uri}: ${error instanceof Error ? error.message : String(error)}`,
      error
    );
  }
}

/**
 * Call a tool on an MCP server
 *
 * @param client - Connected MCP client
 * @param name - Tool name to call
 * @param args - Tool arguments as key-value pairs
 * @returns Promise resolving to tool result
 * @throws MCPClientError if tool call fails
 */
export async function callTool(
  client: Client,
  name: string,
  args: Record<string, any>
): Promise<any> {
  try {
    const result = await client.callTool({
      name,
      arguments: args,
    });
    return result;
  } catch (error) {
    throw new MCPClientError(
      `Failed to call tool ${name}: ${error instanceof Error ? error.message : String(error)}`,
      error
    );
  }
}

/**
 * Subscribe to resource updates
 *
 * @param client - Connected MCP client
 * @param uri - Resource URI to subscribe to
 * @returns Promise resolving when subscription is established
 * @throws MCPClientError if subscription fails
 */
export async function subscribeToResource(client: Client, uri: string): Promise<void> {
  try {
    await client.subscribeResource({ uri });
  } catch (error) {
    throw new MCPClientError(
      `Failed to subscribe to resource ${uri}: ${error instanceof Error ? error.message : String(error)}`,
      error
    );
  }
}
