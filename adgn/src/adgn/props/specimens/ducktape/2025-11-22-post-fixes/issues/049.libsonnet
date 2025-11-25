local I = import '../../specimens/lib.libsonnet';

// iss-049: ChatPane creates two separate MCP clients instead of using shared client

I.issueOneOccurrence(
  rationale= |||
    The `ChatPane.svelte` component creates two separate MCP clients for different
    operations (`chat-pane-client` and `chat-pane-abort-client`) instead of using
    a shared MCP client, duplicating connections and violating the single-client
    architecture.

    **Problem: Two separate MCP client creations**

    **First client (ChatPane.svelte, lines 87-91):**
    ```typescript
    const client = await createMCPClient({
      name: 'chat-pane-client',
      url: `${backendOrigin()}/mcp`,
      token
    })

    const contents = await readResource(client, MCPUris.agentsListUri)
    ```

    **Second client (ChatPane.svelte, lines 124-128):**
    ```typescript
    const client = await createMCPClient({
      name: 'chat-pane-abort-client',
      url: `${backendOrigin()}/mcp`,
      token
    })

    await callTool(client, 'abort_agent', { agent_id: id })
    ```

    **Why this is problematic:**

    1. **Two separate connections**: Creates new MCP clients for each operation
    2. **Connection overhead**: Handshake, authentication, session setup twice
    3. **Resource waste**: Two WebSocket/HTTP connections instead of one
    4. **Inconsistent state**: Two separate MCP sessions
    5. **Violates architecture**: Should use single shared MCP client

    **User's note: "ChatPane has yet another separate mcp client... actually 2 of them"**

    This is the same issue as:
    - `MessageComposer` (issue 044): Creates new client per message
    - `GlobalApprovalsList` (issue 047): Creates separate client

    All components should use a shared MCP client instance.

    **The correct approach: Use shared MCP client**

    ```typescript
    // In shared MCP store:
    import { mcpClient } from '../stores/mcp-client'

    // In ChatPane:
    import { get } from 'svelte/store'
    import { mcpClient } from '../stores/mcp-client'

    async function fetchAgentsList() {
      const client = get(mcpClient)
      if (!client) {
        throw new Error('MCP client not connected')
      }

      const contents = await readResource(client, MCPUris.agentsListUri)
      // Parse and return...
    }

    async function abortAgent(id: string) {
      const client = get(mcpClient)
      if (!client) {
        throw new Error('MCP client not connected')
      }

      await callTool(client, 'abort_agent', { agent_id: id })
    }
    ```

    **Benefits of shared client:**

    1. **Single connection**: One MCP session for all operations
    2. **Connection reuse**: No repeated handshakes/auth
    3. **Consistent state**: All operations see same session
    4. **Resource efficiency**: One WebSocket/HTTP connection
    5. **Centralized management**: Reconnection logic in one place

    **Why two clients in same component is especially bad:**

    Not only does ChatPane create separate clients instead of using shared infrastructure,
    it creates TWO clients within itself:
    - One for reading agents list
    - Another for aborting agents

    There's absolutely no reason these need separate connections. Even if the component
    didn't use a shared client, it should at minimum reuse its own client:

    **Minimum improvement (still not ideal):**
    ```typescript
    let mcpClient: Client | null = null

    async function ensureClient(): Promise<Client> {
      if (!mcpClient) {
        const token = getOrExtractToken()
        if (!token) throw new Error('No auth token')

        mcpClient = await createMCPClient({
          name: 'chat-pane-client',
          url: `${backendOrigin()}/mcp`,
          token
        })
      }
      return mcpClient
    }

    async function fetchAgentsList() {
      const client = await ensureClient()
      const contents = await readResource(client, MCPUris.agentsListUri)
      // ...
    }

    async function abortAgent(id: string) {
      const client = await ensureClient()  // Reuse same client
      await callTool(client, 'abort_agent', { agent_id: id })
    }

    onDestroy(() => {
      // Clean up client if needed
      mcpClient = null
    })
    ```

    **But the best solution: Use shared client from the start**

    ```typescript
    // Shared MCP client store (mcp-client.ts):
    import { writable } from 'svelte/store'
    import type { Client } from '@modelcontextprotocol/sdk/client/index.js'

    export const mcpClient = writable<Client | null>(null)
    export const mcpClientStatus = writable<'disconnected' | 'connecting' | 'connected'>('disconnected')

    export async function connectMCP(url: string, token: string) {
      mcpClientStatus.set('connecting')
      try {
        const client = await createMCPClient({ name: 'app-client', url, token })
        mcpClient.set(client)
        mcpClientStatus.set('connected')
        return client
      } catch (e) {
        mcpClientStatus.set('disconnected')
        throw e
      }
    }

    // App initialization:
    onMount(async () => {
      const token = getOrExtractToken()
      if (token) {
        await connectMCP(`${backendOrigin()}/mcp`, token)
      }
    })

    // ChatPane uses shared client:
    import { mcpClient } from '../stores/mcp-client'

    $: client = $mcpClient

    async function fetchAgentsList() {
      if (!client) {
        throw new Error('MCP not connected')
      }
      const contents = await readResource(client, MCPUris.agentsListUri)
      // ...
    }

    async function abortAgent(id: string) {
      if (!client) {
        throw new Error('MCP not connected')
      }
      await callTool(client, 'abort_agent', { agent_id: id })
    }
    ```

    **Summary of problems:**

    1. Creates first MCP client to read agents list (line 87)
    2. Creates second MCP client to abort agent (line 124)
    3. Two connections to same backend
    4. No client reuse within component
    5. No use of shared client infrastructure
    6. Same problems as MessageComposer (044) and GlobalApprovalsList (047)

    **Recommended actions:**

    1. Create shared MCP client store/context
    2. Initialize client once at app startup
    3. Use shared client in all components
    4. Remove all inline `createMCPClient` calls
    5. Handle reconnection centrally
  |||,
  properties=['use-shared-client', 'avoid-duplicate-connections', 'single-client-instance', 'reuse-resources'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [87, 91],   // First MCP client creation
      [124, 128], // Second MCP client creation
    ],
  },
  gap_note= |||
    This finding illustrates **"single-client-instance"**: network clients (HTTP,
    WebSocket, MCP, database) should be shared across components, not created
    per operation or per component.

    Principle: One client per connection type
    - MCP client: one shared instance
    - HTTP client (fetch): browser handles connection pooling
    - WebSocket: one connection, multiple subscriptions
    - Database: connection pool, not connection per query

    Related to **"reuse-resources"**: connections are expensive resources. Create
    once, reuse many times.

    Why multiple clients are bad:

    **Resource waste:**
    - Each client = handshake + auth + session setup
    - Multiple WebSocket connections
    - Memory overhead per client
    - File descriptor usage

    **Inconsistent state:**
    - Separate sessions don't see each other's state
    - Resource subscriptions on different connections
    - Race conditions between clients

    **Complexity:**
    - Multiple reconnection logic paths
    - Error handling duplicated
    - Token refresh per client
    - Hard to track connection status

    Patterns for shared clients:

    **Svelte store (reactive):**
    ```typescript
    // stores/client.ts
    export const client = writable<Client | null>(null)

    // Component
    $: myClient = $client
    if (myClient) {
      await myClient.call(...)
    }
    ```

    **React context:**
    ```typescript
    const ClientContext = createContext<Client | null>(null)

    function useClient() {
      const client = useContext(ClientContext)
      if (!client) throw new Error('Client not initialized')
      return client
    }
    ```

    **Singleton (simple):**
    ```typescript
    let globalClient: Client | null = null

    export async function getClient(): Promise<Client> {
      if (!globalClient) {
        globalClient = await createClient(...)
      }
      return globalClient
    }
    ```

    Red flags:
    - `createClient()` called in multiple places
    - Each component has its own client
    - Client created per operation
    - No client reuse within component
    - Multiple clients to same backend

    When multiple clients ARE appropriate:
    - Different backends (app API vs auth API)
    - Different auth contexts (user vs service account)
    - Isolation requirements (tenant separation)
    - But document why exception exists
  |||,
)
