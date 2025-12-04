local I = import '../../lib.libsonnet';

// AgentSession.agent_id uses str instead of AgentID domain type

I.issue(
  rationale=|||
    AgentSession.agent_id (runtime.py:234,251) uses str | None, but AgentID is
    the semantic identifier type used throughout codebase.

    Using domain types provides:
    - Type safety: can't mix different ID types
    - Semantic clarity: not just any string, but specific identifier
    - No runtime conversions/validation
    - Clear type contracts in signatures
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [234, 251],
  },
)
