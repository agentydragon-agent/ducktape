local I = import '../../lib.libsonnet';

// iss-054: Multiple components create separate MCP clients instead of using shared client

I.issueMulti(
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

    **ChatPane creates multiple independent clients:**
    Creates TWO clients in the same component - one to list agents,
    another to abort agents. Even without shared infrastructure, these
    operations could reuse a single client instance.

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
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[85, 85]],
      },
      note: 'Creates MCP client to list agents; should use shared client from store/context',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [[87, 91], [124, 128]],
      },
      note: 'Creates TWO separate clients in same component: chat-pane-client (line 87-91) for listing, chat-pane-abort-client (line 124-128) for aborting. Worst offender - not even reusing its own client',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/ChatPane.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [[16, 20]],
      },
      note: 'Creates new MCP client per message send operation; should use shared client',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/MessageComposer.svelte']],
    },
    {
      files: {
        'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [[69, 71]],
      },
      note: 'Creates separate client targeting /api/mcp (non-existent endpoint). Violates 2-level compositor architecture. User suggests: delete component or expose agent-global resource through compositor',
      expect_caught_from: [['adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte']],
    },
  ],
)
