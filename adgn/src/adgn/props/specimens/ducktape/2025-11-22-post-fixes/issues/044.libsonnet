local I = import '../../specimens/lib.libsonnet';

// iss-044: MessageComposer creates second MCP client instead of using shared client

I.issueOneOccurrence(
  rationale= |||
    The `MessageComposer.svelte` component creates a new MCP client connection to
    send user messages, instead of using the shared MCP client that the rest of the
    UI uses to communicate with the 2-level compositor.

    **Problem: Duplicate MCP client connection**

    **Current implementation (MessageComposer.svelte, lines 20-33):**
    ```typescript
    async function sendMessage() {
      if (!message.trim() || !agentId || sending) return

      sending = true
      error = null

      try {
        const token = getOrExtractToken()
        if (!token) {
          throw new Error('Authentication required')
        }

        // Creates a new MCP client every time
        const client = await createMCPClient({
          name: 'message-composer-client',
          url: `${backendOrigin()}/mcp`,
          token
        })

        await callTool(client, 'prompt', { agent_id: agentId, message: message })

        // Clear message on success
        message = ''
      } catch (e) {
        // ... error handling
      }
    }
    ```

    **Why this is problematic:**

    1. **Duplicate connection**: Creates new MCP client per message, separate from shared client
    2. **Resource waste**: Each client has connection overhead (handshake, session, resources)
    3. **Inconsistent state**: Shared client and message client have separate sessions
    4. **Connection churn**: New connection per message instead of reusing
    5. **No connection pooling**: Defeats MCP session benefits

    **Architecture issue:**

    The UI should have a single shared MCP client that talks to the 2-level compositor:
    - **Agent → Agent's functions**: The compositor exposes agent capabilities
    - **Agent functions include**: Tools for sending user messages, reading state, etc.

    Instead, `MessageComposer` creates a parallel connection directly to `/mcp` endpoint.

    **The correct approach:**

    Use the shared MCP client that the UI already maintains:

    ```typescript
    // In stores or shared state:
    import { mcpClient } from '../features/mcp/client-store'

    // In MessageComposer:
    async function sendMessage() {
      if (!message.trim() || !agentId || sending) return

      sending = true
      error = null

      try {
        // Use shared client instead of creating new one
        const client = get(mcpClient)
        if (!client) {
          throw new Error('MCP client not connected')
        }

        // Call tool on shared client
        await callTool(client, 'prompt', { agent_id: agentId, message: message })

        // Clear message on success
        message = ''
      } catch (e) {
        // ... error handling
      } finally {
        sending = false
      }
    }
    ```

    **Question: Which MCP server would this be?**

    In the 2-level compositor architecture:
    - **First level (backend compositor)**: Aggregates MCP servers (runtime, approval, etc.)
    - **Second level (agent → agent functions)**: Agent's capabilities exposed via MCP

    The UI should connect to the **agent's MCP interface**, which would include:
    - `agent.send_message` or `agent.prompt` tool
    - `agent.state` resource
    - `agent.approval` tools (approve, reject)
    - Other agent control operations

    **Possible MCP server names:**
    - `agent_control` or `agent_api`
    - `ui` (if there's a dedicated UI server)
    - `compositor_admin` (if admin tools include message sending)
    - Or the agent itself exposes these tools

    **Current implementation suggests:**

    Looking at the call `await callTool(client, 'prompt', ...)`, there's likely a
    `prompt` tool that should be available on the shared compositor connection.

    **This tool should be part of which server?**

    Given the 2-level architecture, this should probably be:
    1. **Agent control server**: Mounted on compositor, provides `send_message`/`prompt` tool
    2. **UI server**: If there's a `ui` MCP server, it might handle this
    3. **Direct agent tool**: If agent exposes a `prompt` tool directly

    The user asks: **"which mcp server would this be?"**

    The answer depends on the backend architecture. Likely candidates:
    - `compositor_admin` (if it has agent control tools)
    - `ui` (if there's a dedicated UI MCP server)
    - `agent` (if agent itself is exposed as MCP server with `prompt` tool)

    **To determine the correct server:**

    1. Check what MCP servers are mounted in the compositor
    2. Find which server has the `prompt` tool
    3. Ensure shared client connects to that server
    4. Update MessageComposer to use shared client

    **Why duplication happened:**

    1. MessageComposer was added before shared client infrastructure existed
    2. Quick fix: create client inline instead of refactoring to shared connection
    3. No connection pooling or client management

    **Benefits of shared client:**

    1. **Single connection**: One MCP session for all UI interactions
    2. **Connection pooling**: Reuse connection, avoid handshake overhead
    3. **Consistent state**: All tools see same session
    4. **Resource subscriptions**: Shared client can subscribe to resources
    5. **Error handling**: Centralized reconnection logic

    **Implementation notes:**

    If the shared client doesn't currently expose a way to send user messages:
    1. Identify which MCP server has the `prompt` tool
    2. Ensure shared client is connected to that server
    3. Export a convenience function in stores:
       ```typescript
       export async function sendUserMessage(agentId: string, message: string) {
         const client = get(mcpClient)
         if (!client) throw new Error('Not connected')
         return await callTool(client, 'prompt', { agent_id: agentId, message })
       }
       ```
    4. Use that function in MessageComposer

    **Summary:**

    1. MessageComposer should use shared MCP client
    2. Identify which MCP server has the `prompt` tool (likely `agent_control`, `ui`, or `compositor_admin`)
    3. Remove inline `createMCPClient` call
    4. Use shared client from store/context
  |||,
  properties=['avoid-duplication', 'reuse-connections', 'single-client-instance'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/MessageComposer.svelte': [
      [24, 32],  // Creates new MCP client inline
    ],
  },
  gap_note= |||
    This finding illustrates **"reuse-connections"**: creating new network clients
    per operation wastes resources. Use a shared client instance with connection pooling.

    Principle: One client per connection type
    - HTTP clients: shared instance with connection pool
    - WebSocket clients: single connection, multiple operations
    - MCP clients: shared session, multiple tool calls
    - Database connections: connection pool

    Related to **"single-client-instance"**: UI should have one MCP client that
    talks to the compositor, not create clients per component.

    Why duplicate clients are bad:
    - Connection overhead (handshake, auth, session setup)
    - Resource waste (memory, file descriptors)
    - Inconsistent state (separate sessions)
    - Harder to manage (reconnection, error handling)

    Good patterns:

    **Shared client in store:**
    ```typescript
    // client-store.ts
    export const mcpClient = writable<Client | null>(null)

    export async function connectMCP() {
      const client = await createClient(...)
      mcpClient.set(client)
      return client
    }

    // Component.svelte
    import { mcpClient } from '../stores/client-store'
    const client = get(mcpClient)
    await client.callTool('tool', args)
    ```

    **Context-based client:**
    ```typescript
    // MCP provider
    <McpProvider client={client}>
      <App />
    </McpProvider>

    // Consumer
    const client = getContext('mcp-client')
    ```

    **Convenience functions:**
    ```typescript
    // api.ts
    import { mcpClient } from './stores'

    export async function sendMessage(message: string) {
      const client = get(mcpClient)
      if (!client) throw new Error('Not connected')
      return await callTool(client, 'send', { message })
    }

    // Component
    import { sendMessage } from '../api'
    await sendMessage('hello')
    ```

    Bad patterns:

    **Creating client inline:**
    ```typescript
    async function doThing() {
      const client = await createClient(...)  // Every time!
      await client.callTool(...)
    }
    ```

    **Per-component clients:**
    ```typescript
    // Each component creates its own
    const client = await createMCPClient(...)
    ```

    Related question: "which mcp server would this be?"

    In 2-level compositor architecture:
    - Agent → Agent functions (exposed via MCP)
    - Agent functions = tools to control agent (send message, approve, abort)
    - UI connects to agent's MCP interface

    Likely server names:
    - `agent_control`: Agent lifecycle and messaging tools
    - `ui`: Dedicated UI interaction server
    - `compositor_admin`: Admin operations including messaging
    - `agent`: Agent itself exposed as MCP server

    To find the right server:
    - List mounted MCP servers in compositor
    - Find which has `prompt` or `send_message` tool
    - Connect shared client to that server
  |||,
)
