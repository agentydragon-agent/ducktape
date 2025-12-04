local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    AgentIdData is a useless single-field wrapper class (lines 48-50).

    The class wraps a single id field and is used in AgentCreatedMsg.data and
    AgentDeletedMsg.data (lines 55, 61). Single-field wrappers provide no value.
    Pydantic understands NewType aliases like AgentID, so use AgentID directly.

    Replace AgentCreatedMsg.data and AgentDeletedMsg.data types with AgentID directly,
    or rename the field to agent_id: AgentID for clarity. Delete the AgentIdData class.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/agents_ws.py': [
      [48, 50],
      55,
      61,
    ],
  },
)
