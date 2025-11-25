local I = import '../../specimens/lib.libsonnet';

// iss-054: Multiple components create separate MCP clients instead of using shared client

I.issueWithOccurrences(
  rationale= |||
    Four Svelte components each create their own MCP client connections instead of
    using a shared client instance. This violates the 2-level compositor architecture,
    wastes resources, creates inconsistent state, and duplicates connection management.

    **Problem: Separate client per component**

    Components creating independent MCP clients:
    1. **AgentsSidebar** - creates client to list agents
    2. **ChatPane** - creates TWO separate clients (list agents, abort agent)
    3. **MessageComposer** - creates client per message send
    4. **GlobalApprovalsList** - creates client to `/api/mcp` (non-existent endpoint)

    Each creation involves handshake, authentication, session setup, and dedicated connection.

    **Why this is problematic:**

    **Resource waste:**
    - Multiple WebSocket/HTTP connections to same backend
    - Repeated handshake + auth + session setup
    - Memory overhead per client instance
    - File descriptor consumption

    **Architectural violation:**
    - Intended: Single 2-level compositor (UI → shared client → compositor → agents)
    - Actual: Parallel connections bypassing shared architecture
    - GlobalApprovalsList targets non-existent `/api/mcp` endpoint

    **Inconsistent state:**
    - Separate sessions don't see each other's state
    - Resource subscriptions on different connections
    - Race conditions between clients
    - No coordination on updates

    **Maintenance burden:**
    - Multiple reconnection logic paths
    - Error handling duplicated
    - Token refresh per client
    - Hard to track connection status

    **ChatPane is worst offender:**
    Creates TWO clients in same component for no reason - one to list agents,
    another to abort agents. Even without shared infrastructure, should reuse
    its own client.

    **The correct approach: Shared MCP client**

    **Architecture: Single client per application**

    Create global MCP client store/context:
    ```typescript
    // stores/mcp-client.ts
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
    ```

    **Initialize once at app startup:**
    ```typescript
    // App.svelte
    onMount(async () => {
      const token = getOrExtractToken()
      if (token) {
        await connectMCP(`${backendOrigin()}/mcp`, token)
      }
    })
    ```

    **Components use shared client:**
    ```typescript
    // Any component
    import { mcpClient } from '../stores/mcp-client'

    $: client = $mcpClient

    async function fetchData() {
      if (!client) throw new Error('MCP not connected')
      const contents = await readResource(client, uri)
      return parseContents(contents)
    }
    ```

    **Benefits:**
    - Single connection for all operations
    - Connection reuse (no repeated handshakes)
    - Consistent state across components
    - Centralized reconnection logic
    - Easy to track connection status
    - Resource subscriptions work correctly

    **GlobalApprovalsList special case:**
    Component attempts to connect to `/api/mcp` endpoint that doesn't exist.
    Backend comments indicate feature not ready. Should either:
    1. Delete component until backend supports it, OR
    2. Expose global approvals resource through shared compositor

    User notes suggest deleting is cleaner until feature is complete.
  |||,
  properties=['use-shared-client', 'single-connection-instance', 'avoid-duplicate-connections', 'consistent-architecture'],
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[85, 85]],
      },
      note: 'Creates MCP client to list agents; should use shared client from store/context',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[87, 91], [124, 128]],
      },
      note: 'Creates TWO separate clients in same component: chat-pane-client (line 87-91) for listing, chat-pane-abort-client (line 124-128) for aborting. Worst offender - not even reusing its own client',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[16, 20]],
      },
      note: 'Creates new MCP client per message send operation; should use shared client',
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[69, 71]],
      },
      note: 'Creates separate client targeting /api/mcp (non-existent endpoint). Violates 2-level compositor architecture. User suggests: delete component or expose agent-global resource through compositor',
    },
  ],
  gap_note= |||
    This finding illustrates **"single-connection-instance"**: network clients
    (HTTP, WebSocket, MCP, database) should be shared across components, not
    created per operation or per component.

    Principle: One client per connection type
    - MCP client: one shared instance for entire app
    - HTTP client: browser pools connections automatically
    - WebSocket: one connection, multiple subscriptions
    - Database: connection pool, not connection per query

    Related to **"use-shared-client"**: when a system needs external connections,
    centralize client management in store/context/service.

    Related to **"consistent-architecture"**: when architecture defines a pattern
    (2-level compositor with shared client), all components must follow it.

    Why multiple clients are bad:

    **Per-component clients:**
    - Each component creates on mount
    - Handshake + auth + session repeated
    - N components = N connections
    - Unmount doesn't guarantee cleanup

    **Per-operation clients:**
    - MessageComposer creates client per send
    - Extreme waste: handshake per message
    - No connection reuse
    - Defeats purpose of persistent connections

    **Two clients in same component (ChatPane):**
    - Most egregious violation
    - Not even architectural ignorance
    - Pure redundancy within one file

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

    **Singleton (simple but less testable):**
    ```typescript
    let globalClient: Client | null = null

    export async function getClient(): Promise<Client> {
      if (!globalClient) {
        globalClient = await createClient(...)
      }
      return globalClient
    }
    ```

    **Dependency injection (testable):**
    ```typescript
    class AgentsService {
      constructor(private client: Client) {}

      async listAgents() {
        return await this.client.readResource(...)
      }
    }

    // Tests inject mock client
    ```

    When multiple clients ARE appropriate:
    - Different backends (app API vs auth API)
    - Different auth contexts (user vs service account)
    - Isolation requirements (tenant separation)
    - But document why exception exists

    Red flags:
    - `createClient()` called in multiple components
    - Client created in component mount hook
    - Client created per operation/message
    - Multiple clients to same backend
    - No client reuse within component

    2-level compositor architecture:
    - Level 1: Backend compositor aggregates MCP servers
    - Level 2: UI connects once to compositor
    - All agent functions accessible through single client
    - Parallel connections bypass this design

    Cost of architectural violations:
    - Resource waste (connections, memory)
    - State inconsistencies (separate sessions)
    - Maintenance burden (multiple code paths)
    - User confusion (why multiple endpoints?)
    - Hard to debug (which client failed?)

    Migration path:
    1. Create shared client store/context
    2. Initialize client at app startup
    3. Replace component `createMCPClient` with store access
    4. Remove per-component/per-operation clients
    5. Test connection lifecycle (startup, reconnect, errors)
    6. Delete GlobalApprovalsList or fix backend

    Special case (GlobalApprovalsList):
    - Targets /api/mcp endpoint that doesn't exist
    - Backend comments: "TODO: Register websocket routes"
    - Feature incomplete, component non-functional
    - User recommendation: delete until backend ready
    - If keeping: expose via compositor, use shared client

    Benefits of shared client:
    - One connection for all operations
    - Connection reuse, no wasted handshakes
    - Consistent state across UI
    - Centralized error handling
    - Easier to add features (logging, metrics, retries)
    - Simpler testing (inject one mock)
  |||,
)
