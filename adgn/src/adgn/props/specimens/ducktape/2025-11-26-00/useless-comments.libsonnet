local I = import '../../lib.libsonnet';

// Merged: useless-comments (Python), useless-ts-comments (TypeScript)
// Both describe comments that merely restate obvious code

I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ChatPane.svelte'],
  ],
  rationale= |||
    Three files have comments that merely restate what the code obviously does. Python
    examples in cli.py lines 484, 717-719, 722: "Capture -a/--all", "Parse flags from
    passthru", "Logging and config" just describe the next lines. TypeScript examples
    in AgentsSidebar.svelte lines 73, 86, 89 and ChatPane.svelte lines 79, 84, 107:
    "Get singleton MCP client" → getMCPClient(), "Subscribe to agents list updates"
    → subscribeToResource, etc.

    Problems: Noise makes code harder to scan, redundant with well-named functions,
    maintenance burden (must update when code changes), no added value (don't explain
    rationale, caveats, or non-obvious behavior).

    Delete all these comments. Only add comments explaining WHY something is done,
    caveats, workarounds, or complex logic that isn't self-evident. Benefits: cleaner
    scannable code, no maintenance overhead, focus on actual insights when present.
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
