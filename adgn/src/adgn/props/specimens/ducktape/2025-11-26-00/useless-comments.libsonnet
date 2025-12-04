local I = import '../lib.libsonnet';

// Merged: useless-comments (Python), useless-ts-comments (TypeScript)
// Both describe comments that merely restate obvious code

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Multiple locations in both Python and TypeScript have comments that merely restate
    what the code obviously does, providing no additional value or context.

    **Python examples** (cli.py):
    ```python
    # Capture -a/--all (staging flag) to remove from passthru
    # Logging and config
    # Parse flags from passthru (those not handled by argparse)
    ```

    Problems:
    - "Capture -a/--all" documents historical behavior, not current code
    - "Logging and config" just restates what the next lines do
    - "Parse flags" is misleading (some flags are from argparse, not passthru)

    **TypeScript examples** (AgentsSidebar.svelte, ChatPane.svelte):
    ```typescript
    // Get singleton MCP client
    mcpClient = await getMCPClient()

    // Subscribe to agents list updates
    await subscribeToResource(mcpClient, MCPUris.agentsListUri)

    // Fetch initial list
    await fetchAgentsList()

    // Parse the resource contents
    if (Array.isArray(contents) && contents.length > 0) {
    ```

    Problems:
    - Comments literally just describe the function name
    - "Get singleton MCP client" → `getMCPClient()`
    - "Subscribe to agents list updates" → `subscribeToResource(...agentsListUri)`
    - No explanation of WHY, WHEN, or any subtlety

    **Why these are problematic:**
    - **Noise**: Make code harder to scan without providing information
    - **Redundant**: Well-named functions are self-documenting
    - **Maintenance burden**: Must update comments when code changes
    - **No added value**: They don't explain rationale, caveats, or non-obvious behavior

    **Recommended fix:**
    Delete all these comments. Function names and code structure are sufficient.

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
    ```

    **Benefits:**
    - Cleaner, more scannable code
    - No maintenance overhead for obvious comments
    - Focus on actual insights when comments are present
    - Follows principle: comments should explain WHY, not WHAT
  |||,

  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [484, 484],  // "Capture -a/--all (staging flag) to remove from passthru"
      [717, 719],  // "Parse flags from passthru (those not handled by argparse)"
      [722, 722],  // "Logging and config"
    ],
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [
      [73, 73],    // "Get singleton MCP client"
      [86, 86],    // "Subscribe to agents list updates"
      [89, 89],    // "Fetch initial list"
    ],
    'adgn/src/adgn/agent/web/src/components/ChatPane.svelte': [
      [79, 79],    // "Get singleton MCP client"
      [84, 84],    // "Parse the resource contents"
      [107, 107],  // "Get singleton MCP client" (duplicate)
    ],
  },
)
