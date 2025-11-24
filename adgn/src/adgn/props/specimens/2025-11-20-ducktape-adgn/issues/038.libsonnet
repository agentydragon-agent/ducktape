local I = import '../../specimens/lib.libsonnet';

// iss-038: AgentSession.agent_id should be AgentID type

I.issueOneOccurrence(
  rationale=|||
    AgentSession uses str for agent_id parameter and field (runtime.py:234,251):

    def __init__(
        self,
        ...
        agent_id: str | None = None,
        ...
    ) -> None:
        ...
        self.agent_id: str | None = agent_id

    AgentID is a NewType for semantic agent identifiers used throughout the codebase.
    Using raw str loses type safety and semantic meaning.

    Should be:
    agent_id: AgentID | None = None
    ...
    self.agent_id: AgentID | None = agent_id

    Benefits:
    - Type consistency: AgentID used elsewhere in codebase
    - Semantic clarity: not just any string, an agent identifier
    - Type safety: can't accidentally pass wrong string type
    - Matches patterns in registry.py, persist layer, etc.

    Same issue as #013 (Agent.id should be AgentID in models), but for runtime layer.
  |||,
  properties=['type-correctness-and-specificity'],
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      234,          // agent_id: str | None parameter
      251,          // self.agent_id: str | None field
    ],
  },
)
