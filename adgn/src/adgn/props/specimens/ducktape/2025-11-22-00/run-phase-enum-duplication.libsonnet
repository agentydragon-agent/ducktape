local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Three run phase/status enums exist with different granularity, causing name
    collisions, unclear subset relationships, and lost information when converting.

    status_shared.py RunPhase (7 states): distinguishes TOOLS_RUNNING from SAMPLING
    via determine_run_phase() logic (lines 42-56). mcp_bridge/types.py RunPhase
    (3 states): cannot make this distinction. protocol.py RunStatus (7 states):
    lifecycle-focused (STARTING/FINISHED) rather than execution phase.

    Impact: Name collision (two RunPhase enums), conversion overhead, coarser enums
    lose information (can't distinguish tool execution from sampling).

    Use status_shared.RunPhase everywhere. Delete mcp_bridge RunPhase. If RunStatus
    tracks a different dimension (lifecycle vs execution phase), rename to clarify
    (e.g., AgentLifecycle). For code needing coarser granularity, write mapping
    functions from the comprehensive enum.

    Principle: One enum per dimension, most granular wins. Derive coarser projections
    rather than maintaining multiple enums.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [
      [18, 25],   // Most comprehensive RunPhase (7 states)
      [42, 56],   // determine_run_phase with fine-grained logic
    ],
    'adgn/src/adgn/agent/mcp_bridge/types.py': [
      [17, 21],   // Less granular RunPhase (3 states, should be deleted)
    ],
    'adgn/src/adgn/agent/server/protocol.py': [
      [80, 87],   // RunStatus (different granularity, possibly different concern)
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/status_shared.py'],
    ['adgn/src/adgn/agent/mcp_bridge/types.py'],
    ['adgn/src/adgn/agent/server/protocol.py'],
  ],
)
