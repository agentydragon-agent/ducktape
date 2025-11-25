local I = import '../../specimens/lib.libsonnet';

// iss-047: GlobalApprovalsList uses separate MCP client instead of 2-level compositor

I.issueOneOccurrence(
  rationale= |||
    The `GlobalApprovalsList.svelte` component creates its own separate MCP client
    targeting `/api/mcp`, which contradicts the intended 2-level compositor architecture
    where everything should be mounted for all agents through a shared compositor
    and agent registry.

    **Problem: Separate MCP client breaks architectural intent**

    **Current implementation (GlobalApprovalsList.svelte, lines 69-71):**
    ```typescript
    // Connect to MCP server (requires backend to expose MCP endpoint)
    // In a full implementation, this would connect to something like:
    // http://localhost:8765/api/mcp
    mcpClient = await createMCPClient({
      name: 'global-approvals-ui',
      url: `${window.location.origin}/api/mcp`,
      token
    })
    ```

    **Why this breaks architecture:**

    1. **Separate connection**: Creates new MCP client independent of shared compositor
    2. **Bypasses 2-level compositor**: Should go through shared agent → agent's functions
    3. **No agent registry integration**: Doesn't use shared agent registry
    4. **Inconsistent access**: Other components use shared client, this doesn't
    5. **Duplicate session**: Separate session state from main UI connection

    **Intended architecture: 2-level compositor**

    The 2-level compositor is designed to:
    - **Level 1 (backend)**: Compositor aggregates MCP servers (runtime, approval, etc.)
    - **Level 2 (frontend)**: UI connects to compositor, sees all agent functions
    - **Shared registry**: All agents and their states accessible through one connection
    - **Single client**: UI has one MCP client that talks to everything

    Instead, `GlobalApprovalsList` creates a parallel connection to `/api/mcp`.

    **User's note: "inconsistent architecture/implementation"**

    The user identifies two possible resolutions:

    **Resolution 1: Delete GlobalApprovalsList component**

    User notes: **"(i suspect global approvals list just does not work yet and
    would be easier to just delete)"**

    If the component is incomplete/non-functional, removing it is cleanest:
    - Eliminates architectural inconsistency
    - Removes dead code
    - Avoids confusion about how approvals should work

    **Resolution 2: Properly expose agent-global resource**

    User suggests: **"another: properly expose some agent-global resource (and its
    notifications) that actually exposes those approval events without any specific
    agent."**

    This would require:
    1. **Agent-global approvals resource**: `resources://approvals/global/pending`
    2. **Mounted on shared compositor**: Available through main UI connection
    3. **Resource notifications**: Subscribe to updates via shared client
    4. **Tools on compositor**: `approve_global`, `reject_global` tools

    **Example of proper architecture:**

    ```typescript
    // In shared MCP store/context:
    export const mcpClient = writable<Client | null>(null)

    // GlobalApprovalsList uses shared client:
    import { mcpClient } from '../stores/mcp-client'

    async function fetchApprovals() {
      const client = get(mcpClient)
      if (!client) {
        throw new Error('MCP client not connected')
      }

      // Use shared client to read global resource
      const contents = await readResource(client, 'resources://approvals/global/pending')
      return parseApprovalContents(contents)
    }

    async function handleApprove(agentId: string, callId: string) {
      const client = get(mcpClient)
      if (!client) return

      // Call tool on shared compositor
      await callTool(client, 'approvals_global.approve', {
        agent_id: agentId,
        call_id: callId
      })
    }

    // Subscribe to updates using shared client
    onMount(async () => {
      const client = get(mcpClient)
      if (client) {
        await subscribeToResource(client, 'resources://approvals/global/pending')
      }
    })
    ```

    **What backend needs to support this:**

    1. **Global approvals server**: MCP server that aggregates approvals across all agents
    2. **Mounted on compositor**: Available at `approvals_global` or similar
    3. **Resources**:
       - `resources://approvals/global/pending` - all pending approvals
       - `resources://approvals/global/history` - approval history
    4. **Tools**:
       - `approvals_global.approve(agent_id, call_id)`
       - `approvals_global.reject(agent_id, call_id, reason)`
    5. **Notifications**: Emit `ResourceUpdated` when approvals change

    **Current backend status:**

    Based on the comments in the component (lines 55-64):
    ```typescript
    /**
     * NOTE: This requires the backend to expose an MCP StreamableHTTP endpoint.
     * The current backend doesn't expose this yet - the MCP bridge server
     * exists but isn't mounted at an HTTP endpoint accessible from the frontend.
     *
     * To enable this, the backend would need to:
     * 1. Mount the MCP bridge server at an HTTP endpoint (e.g., /api/mcp)
     * 2. Use FastMCP's StreamableHTTP transport
     * 3. Accept bearer token authentication
     */
    ```

    The backend infrastructure may not be ready for this component.

    **Recommendation: Delete GlobalApprovalsList**

    Given:
    - Component doesn't work yet (per comments)
    - Backend not ready
    - Architectural inconsistency
    - User suspects "easier to just delete"

    The cleanest solution is to remove the component until:
    1. Backend properly exposes global approvals resource
    2. Resource is mounted on shared compositor
    3. UI can use shared MCP client

    **If keeping the component:**

    1. Mark as experimental/non-functional
    2. Add clear documentation of what's missing
    3. Use shared client (even if resource doesn't exist yet)
    4. Handle missing backend gracefully

    **Related issue: Multiple components with separate MCP clients**

    This same pattern appears in:
    - `MessageComposer.svelte` (issue 044)
    - `ChatPane.svelte` (user noted: "actually 2 of them")

    All of these should use the shared MCP client architecture.

    **Summary of problems:**

    1. Creates separate MCP client instead of using shared one
    2. Targets `/api/mcp` which may not exist
    3. Bypasses 2-level compositor architecture
    4. No integration with shared agent registry
    5. Component likely doesn't work (per backend comments)

    **Recommended action:**

    Delete the component and implement global approvals properly when backend is ready:
    1. Backend exposes `resources://approvals/global/pending`
    2. Resource mounted on shared compositor
    3. UI uses shared MCP client
    4. Resource notifications work
    5. Re-add component using proper architecture
  |||,
  properties=['consistent-architecture', 'use-shared-client', 'avoid-parallel-connections', 'remove-incomplete-features'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [69, 71],    // Separate MCP client creation
      [55, 64],    // Comment about missing backend
    ],
  },
  gap_note= |||
    This finding illustrates **"consistent-architecture"**: when a system has an
    architectural pattern (2-level compositor with shared client), all components
    should follow it. Don't create exceptions that bypass the architecture.

    Principle: Architectural consistency > local convenience
    - If architecture says "shared client", use shared client
    - If feature doesn't fit architecture, fix architecture or defer feature
    - Don't create parallel systems that work differently

    Related to **"remove-incomplete-features"**: code that doesn't work yet and
    contradicts architecture should be removed, not left in codebase.

    Why parallel systems are harmful:
    - Confusing (which pattern to follow?)
    - Duplication (multiple clients, sessions)
    - Inconsistent behavior (different error handling, timeouts)
    - Harder to maintain (changes need multiple updates)
    - Resource waste (multiple connections)

    Correct pattern for global features in compositored architecture:

    **Backend (Python):**
    ```python
    # Global approvals server
    class GlobalApprovalsServer:
        @mcp.resource("approvals/global/pending")
        async def pending_approvals(self) -> list[Approval]:
            # Aggregate from all agents
            return await self.registry.get_all_pending_approvals()

        @mcp.tool()
        async def approve_global(self, agent_id: str, call_id: str):
            agent = await self.registry.get_agent(agent_id)
            await agent.approve(call_id)

    # Mount on compositor
    compositor.mount("approvals_global", GlobalApprovalsServer(registry))
    ```

    **Frontend (TypeScript):**
    ```typescript
    // Use shared client
    import { mcpClient } from '../stores/mcp'

    async function fetchGlobalApprovals() {
      const client = get(mcpClient)
      const resource = await client.readResource('approvals/global/pending')
      return parseApprovals(resource)
    }

    async function approveGlobal(agentId: string, callId: string) {
      const client = get(mcpClient)
      await client.callTool('approvals_global.approve', { agent_id: agentId, call_id: callId })
    }
    ```

    **When to create separate client:**
    - Never in the same architecture
    - Only for truly independent systems (different auth, different backend)
    - Document why exception is necessary

    **When feature doesn't fit architecture:**
    1. Evaluate if architecture needs to change
    2. If yes: update architecture, then implement feature
    3. If no: defer feature until architecture can support it
    4. Don't hack around architecture

    Signs of architectural violations:
    - Component creates its own client when shared one exists
    - Bypasses established patterns "just for this one case"
    - Comments like "TODO: use shared client"
    - Duplicate infrastructure (multiple clients, sessions, connections)

    Resolution options ranked:
    1. **Best**: Delete incomplete feature, implement properly later
    2. **OK**: Mark as experimental, fix to use proper architecture
    3. **Bad**: Leave as-is with architectural violation
    4. **Worst**: Let violation spread to other components
  |||,
)
