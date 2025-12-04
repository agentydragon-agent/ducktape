local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 284-294 assign `run_phase` using string literals ("idle", "waiting_approval",
    "sampling") instead of a proper enum, losing type safety and enabling typos.

    Problems: No type safety (typos like "wating_approval" won't be caught), no
    exhaustiveness checking, no IDE autocomplete, magic strings scattered across code,
    hard to discover valid values, inconsistent with other status fields (AgentMode,
    ServerStatus, ProposalStatus, etc. use enums).

    Define a RunPhase StrEnum with IDLE/WAITING_APPROVAL/SAMPLING values and use it
    throughout. Update the Pydantic model to type run_phase as RunPhase instead of str.
    Benefits: type-safe phase values, IDE autocomplete, single source of truth,
    self-documenting, consistent with codebase patterns, easier refactoring, validation
    at Pydantic boundary.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [284, 294],  // run_phase assignment with string literals
      [284, 284],  // run_phase = "idle"
      [292, 292],  // run_phase = "waiting_approval"
      [294, 294],  // run_phase = "sampling"
    ],
  },
)
