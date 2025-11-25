local I = import '../../specimens/lib.libsonnet';

// iss-045: GlobalApprovalsList explicit constructions should use factories with defaults

I.issueOneOccurrence(
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
  properties=['use-factories', 'avoid-boilerplate', 'provide-defaults', 'encapsulate-construction'],
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
  gap_note= |||
    This finding illustrates **"use-factories"**: repeated explicit object
    construction should use factory functions or builders with reasonable defaults.

    Principle: Encapsulate construction complexity
    - Factory functions provide default values
    - Builders enable fluent construction
    - Helpers centralize common patterns
    - Test factories make testing easier

    Related to **"provide-defaults"**: functions should have reasonable default
    values for optional parameters, reducing boilerplate at call sites.

    Related to **"encapsulate-construction"**: hide construction details behind
    factory functions, making code easier to maintain and test.

    Patterns for construction:

    **Factory function:**
    ```typescript
    function createUser(name: string, options?: Partial<User>): User {
      return {
        id: uuid(),
        name,
        email: options?.email ?? `${name}@example.com`,
        role: options?.role ?? 'user',
        createdAt: options?.createdAt ?? new Date()
      }
    }
    ```

    **Builder pattern:**
    ```typescript
    class UserBuilder {
      private user: Partial<User> = {}

      withName(name: string) {
        this.user.name = name
        return this
      }

      withRole(role: string) {
        this.user.role = role
        return this
      }

      build(): User {
        return {
          id: this.user.id ?? uuid(),
          name: this.user.name ?? 'Unknown',
          email: this.user.email ?? 'user@example.com',
          role: this.user.role ?? 'user',
          createdAt: this.user.createdAt ?? new Date()
        }
      }
    }

    const user = new UserBuilder().withName('Alice').withRole('admin').build()
    ```

    **Test factory:**
    ```typescript
    export function createTestApproval(overrides?: Partial<Approval>): Approval {
      return {
        agent_id: 'test-agent',
        tool_call: {
          name: 'test_tool',
          call_id: 'test-call',
          args_json: '{}'
        },
        timestamp: '2024-01-01T00:00:00Z',
        ...overrides
      }
    }

    // Test:
    const approval = createTestApproval({ agent_id: 'my-agent' })
    ```

    Benefits for testing:
    - **Readable**: `createTestUser({ role: 'admin' })` vs full object literal
    - **Maintainable**: Change defaults in one place
    - **Flexible**: Override only what matters for test
    - **Type-safe**: Factory enforces required fields

    Red flags:
    - Repeated object literals with same/similar values
    - Tests creating complex objects inline
    - Constructor calls with many parameters
    - Copy-paste of initialization code
  |||,
)
