local I = import '../../lib.libsonnet';

// iss-045: GlobalApprovalsList explicit constructions should use factories with defaults

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    The `GlobalApprovalsList.svelte` component contains extensive explicit tool and
    resource constructions that should use factories or helper functions with
    reasonable default values for cleaner, more maintainable test code.

    **Problem: Verbose explicit constructions without helpers**

    **Current implementation examples (throughout component):**

    **Line 69 - Explicit MCP client creation:**
    ```typescript
    mcpClient = await createMCPClient({
      name: 'global-approvals-ui',
      url: `${window.location.origin}/api/mcp`,
      token
    })
    ```

    **Line 78 - Explicit resource subscription:**
    ```typescript
    await subscribeToResource(mcpClient, MCPUris.approvalsPendingUri)
    ```

    **Line 107 - Explicit resource reading:**
    ```typescript
    const contents = await readResource(mcpClient, MCPUris.approvalsPendingUri)
    ```

    **Lines 115-121 - Explicit approval object construction:**
    ```typescript
    parsedApprovals.push({
      agent_id: data.agent_id,
      tool_call: data.tool_call,
      timestamp: data.timestamp
    })
    ```

    **Lines 138-142 - Explicit tool call:**
    ```typescript
    await callTool(mcpClient, 'approve_tool_call', {
      agent_id: agentId,
      call_id: callId
    })
    ```

    **Lines 175-180 - Another explicit tool call:**
    ```typescript
    await callTool(mcpClient, 'reject_tool_call', {
      agent_id: rejectAgentId,
      call_id: rejectCallId,
      reason: rejectReason
    })
    ```

    **Why this is problematic:**

    1. **Verbose boilerplate**: Repeated MCP client creation, tool calls, resource reads
    2. **No default values**: Every call must specify all parameters
    3. **Hard to test**: Can't easily mock or stub without recreating full objects
    4. **Duplication**: Same patterns repeated across component
    5. **Fragile**: Changes to MCP API require updating many call sites

    **The correct approach: Create factories and helpers**

    Extract repeated patterns into helper functions with defaults:

    1. **MCP client creation**: Factory like `createApprovalsClient(options?)` with
       default name/url/token
    2. **Approval operations**: Helpers like `fetchPendingApprovals(client)`,
       `approveToolCall(client, agentId, callId)`, etc.
    3. **Approval parsing**: `parseApprovalContents(contents)` with a
       `createApproval(data)` helper providing default timestamp

    Benefits: default values, centralized logic, easier testing (mock helpers instead
    of raw MCP calls), type safety, less duplication, easier refactoring.

    **When to create factories/helpers:**

    - **Repeated patterns** (3+ similar constructions)
    - **Complex initialization** (multiple required fields)
    - **Testing needed** (want to mock/stub behavior)
    - **Default values useful** (most calls use same values)
    - **Encapsulation** (hide implementation details)

    **When explicit construction is OK:**

    - **One-off use** (only appears once)
    - **All parameters vary** (no common defaults)
    - **Testing not needed** (simple DTO/value object)
    - **Simple structure** (< 3 fields, no nesting)

    **Related patterns:**

    - **Builder pattern**: For complex construction with many optional fields
    - **Factory with options**: `Partial<T> & Required<Pick<T, 'key'>>` for flexible defaults

    **User's note: "lots of explicit tool and resource constructions, those should
    use some factories / helpers with reasonable/helpful default values."**

    This applies throughout the component:
    - MCP client creation (line 69)
    - Resource subscription (line 78)
    - Resource reading (line 107)
    - Approval parsing (lines 115-121)
    - Tool calls (lines 138-142, 175-180)

    All of these should have helper functions with sensible defaults.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [69, 71],    // Explicit MCP client creation
      [78, 78],    // Explicit resource subscription
      [107, 107],  // Explicit resource reading
      [115, 121],  // Explicit approval construction
      [138, 142],  // Explicit approve tool call
      [175, 180],  // Explicit reject tool call
    ],
  },
)
