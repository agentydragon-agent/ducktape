local I = import '../../lib.libsonnet';

// Merged: agentbrief-id-type, agentstatusdata-id-type
// Both describe fields that represent agent IDs using str instead of AgentID newtype

I.issue(
  rationale= |||
    Multiple fields that semantically represent agent IDs use generic str type instead
    of the AgentID newtype from adgn.agent.types.

    **Two occurrences in agents_ws.py:**

    **1. AgentBrief.id (line 30)**
    Field defined as `id: str` but semantically represents an agent ID.

    **2. AgentStatusData.id (line 66)**
    Field defined as `id: str` but semantically represents an agent ID.

    **Problem with using str for typed IDs:**
    - Loss of type safety (can pass any string)
    - No semantic clarity (doesn't indicate this is specifically an agent ID)
    - Can't enforce ID format constraints
    - Harder to track ID flow through codebase

    **Correct approach: Use AgentID newtype**

    Replace `id: str` with `id: AgentID` and ensure AgentID is imported from
    adgn.agent.types. Pydantic handles NewType aliases correctly for validation and
    serialization.

    Benefits:
    - Type checker catches misuse (passing non-agent-ID strings)
    - Clear semantic meaning (this is specifically an agent ID)
    - Can grep for AgentID to find all agent ID usage
    - Consistent with codebase typing conventions
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/agents_ws.py': [
      [30, 30],  // AgentBrief.id: str → AgentID
      [66, 66],  // AgentStatusData.id: str → AgentID
    ],
  },
)
