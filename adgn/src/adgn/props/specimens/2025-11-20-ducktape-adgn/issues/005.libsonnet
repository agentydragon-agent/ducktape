local I = import '../../specimens/lib.libsonnet';

// iss-005: get_local_runtime should use walrus operator to avoid intermediate variable
//
// Context:
// - Method retrieves agent from registry and conditionally accesses local_runtime
// - Uses two lines: first assigns to variable, second uses it in ternary
//
// Current (server.py:162-163):
//   agent = self._agents[agent_id].agent
//   return agent.local_runtime if agent else None
//
// Should use walrus operator (PEP 572):
//   return agent.local_runtime if (agent := self._agents[agent_id].agent) else None
//
// Benefits:
// - Single expression (no intermediate variable)
// - Clearer intent: assignment scoped to conditional
// - Follows modern Python idiom for "assign and check" pattern
//
// Properties violated:
// 1. python/walrus: Walrus operator preferred for assign-and-use-once patterns
// 2. no-oneoff-vars-and-trivial-wrappers: Intermediate variable used only once
// 3. modern-python-idioms: Walrus is the idiomatic approach (Python 3.8+)

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
  properties=['python/walrus', 'no-oneoff-vars-and-trivial-wrappers', 'python/modern-python-idioms'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [162, 163],   // Two-line pattern that should be single walrus expression
    ],
  },
)
