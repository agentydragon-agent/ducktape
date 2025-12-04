local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 162-168 define AgentApprovalsHistory with a redundant `count` field that's
    trivially computable from the `timeline` and `pending` lists already in the response
    (count = len(timeline) + len(pending)). Lines 446-450 compute and construct this
    redundant field.

    Problems: Trivially computable by clients in one line, redundant information wastes
    bandwidth, inconsistency risk if lists are modified or computation has bugs, violates
    single source of truth (data in lists, count is derived), makes tests more brittle
    (must verify count matches lengths).

    Remove count field from model and construction. Clients compute it when needed.
    Benefits: eliminates redundant data, smaller payloads, no sync risk, simpler model,
    encourages lazy evaluation, one less field to maintain and test.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [168, 168],  // Redundant count field in model
      [446, 450],  // Count computation and construction
      [447, 447],  // Explicit count calculation line
    ],
  },
)
