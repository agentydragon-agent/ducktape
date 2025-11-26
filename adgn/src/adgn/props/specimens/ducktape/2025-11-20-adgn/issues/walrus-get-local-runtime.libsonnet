local I = import '../../specimens/lib.libsonnet';

// iss-005: get_local_runtime should use walrus operator

I.issueOneOccurrence(
  rationale=|||
    Method uses two-line pattern for assign-and-conditional-access:
    1. Assign to intermediate variable
    2. Use variable in ternary expression

    This is the exact use case for walrus operator (:=), introduced in PEP 572.
    The variable is used only once, making it a trivial wrapper.

    Walrus operator benefits:
    - Single expression instead of statement + expression
    - Assignment scoped to conditional (clearer lifetime)
    - Reduces line count without hurting readability
    - Follows modern Python idioms for "assign and check" patterns

    Conversion:
    return agent.local_runtime if (agent := self._agents[agent_id].agent) else None
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [162, 163],   // Two-line pattern that should be single walrus expression
    ],
  },
)
