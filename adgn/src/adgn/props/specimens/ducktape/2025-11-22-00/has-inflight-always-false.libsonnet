local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    `mcp_has_inflight` parameter is always `False` (runtime.py:249,
    status_shared.py:162) with comments "not exposed", making
    `RunPhase.TOOLS_RUNNING` unreachable. The `determine_run_phase()`
    function checks this parameter but it's always False.

    Impact: unreachable enum value, misleading signature (suggests detection
    works), documentation claims "MCP tools executing" but never happens,
    UI may show wrong phase.

    Options: (1) implement tracking (McpManager tracks inflight calls in a
    set, add/remove on call_tool entry/exit), or (2) remove feature (delete
    TOOLS_RUNNING enum value and mcp_has_inflight parameter).

    Principle: no dead parameters. If a parameter is always constant, either
    implement the varying logic or remove it.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [249, 249],   // has_inflight = False with comment "not exposed at this layer"
      [253, 253],   // Passing False to determine_run_phase
    ],
    'adgn/src/adgn/agent/server/status_shared.py': [
      [42, 56],     // determine_run_phase has mcp_has_inflight parameter
      [162, 163],   // has_inflight = False with comment "not exposed here"
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/runtime.py'],
    ['adgn/src/adgn/agent/server/status_shared.py'],
  ],
)
