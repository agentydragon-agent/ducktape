local I = import '../../specimens/lib.libsonnet';

// iss-018: Useless TypeScript comments that restate code

I.issueOneOccurrence(
  rationale= |||
    Multiple TypeScript files have useless comments that merely restate what the following
    line does, providing no additional value or context.

    **AgentsSidebar.svelte:**
    ```typescript
    // Get singleton MCP client
    mcpClient = await getMCPClient()

    // Subscribe to agents list updates
    await subscribeToResource(mcpClient, MCPUris.agentsListUri)

    // Fetch initial list
    await fetchAgentsList()
    ```

    **ChatPane.svelte:**
    ```typescript
    // Get singleton MCP client
    const client = await getMCPClient()

    // Parse the resource contents
    if (Array.isArray(contents) && contents.length > 0) {

    // Get singleton MCP client
    const client = await getMCPClient()
    ```

    **Problems:**
    1. **Redundant**: Comments literally just describe the function name
       - "Get singleton MCP client" → `getMCPClient()`
       - "Subscribe to agents list updates" → `subscribeToResource(...agentsListUri)`
       - "Fetch initial list" → `fetchAgentsList()`
       - "Parse the resource contents" → parsing code
    2. **No added value**: They don't explain *why*, *when*, or any subtlety
    3. **Noise**: Make code harder to scan without providing information
    4. **Maintenance burden**: Must update comments when code changes

    **Correct approach:**
    Delete all these comments. Well-named functions are self-documenting.

    Only add comments when they explain:
    - **Why** something is done (rationale/context)
    - **Caveats** or non-obvious behavior
    - **Workarounds** for bugs or limitations
    - **Complex** logic that isn't self-evident

    **Good comment examples (not in this code):**
    ```typescript
    // Retry on 503 because backend needs time to warm up cold instances
    await retryRequest()

    // HACK: Resource list doesn't update on its own; must poll
    setInterval(fetchList, 5000)

    // Safari requires explicit user gesture for clipboard access
    if (isSafari) await navigator.clipboard.writeText(text)
    ```

    These comments explain *why* or *what's non-obvious*, not just *what*.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [
      [73, 73],   // "Get singleton MCP client"
      [86, 86],   // "Subscribe to agents list updates"
      [89, 89],   // "Fetch initial list"
    ],
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [79, 79],   // "Get singleton MCP client"
      [84, 84],   // "Parse the resource contents"
      [107, 107], // "Get singleton MCP client" (duplicate)
    ],
  },
)
