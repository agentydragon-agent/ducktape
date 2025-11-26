local I = import '../../specimens/lib.libsonnet';

// iss-006: Should use AgentID type instead of str; delete useless AgentIdData wrapper

I.issueOneOccurrence(
  rationale= |||
    Multiple issues related to AgentID type usage in agents_ws.py:

    **Issue 1: AgentStatusData.id should be AgentID, not str (line 66)**

    ```python
    class AgentStatusData(BaseModel):
        id: str  # Should be: AgentID
        live: bool
        ...
    ```

    The field represents an agent ID semantically, but is typed as generic `str`. The
    codebase has an `AgentID` type (from adgn.agent.types) that should be used for
    type safety and semantic clarity.

    **Issue 2: AgentBrief.id should also be AgentID (line 30)**

    ```python
    class AgentBrief(BaseModel):
        id: str  # Should be: AgentID
        ...
    ```

    Same issue - represents an agent ID but typed as generic string.

    **Issue 3: AgentIdData is a useless wrapper (lines 48-50)**

    ```python
    class AgentIdData(BaseModel):
        id: str
        model_config = ConfigDict(extra="forbid")
    ```

    This class is used in `AgentCreatedMsg.data` and `AgentDeletedMsg.data` (lines 55, 61).
    It's a single-field wrapper around an ID, which provides no value. Pydantic understands
    NewType aliases like AgentID, so we can use AgentID directly without a wrapper.

    **Better approach:**
    ```python
    class AgentCreatedMsg(BaseModel):
        type: Literal["agent_created"] = "agent_created"
        data: AgentID  # Or: agent_id: AgentID
        model_config = ConfigDict(extra="forbid")

    class AgentDeletedMsg(BaseModel):
        type: Literal["agent_deleted"] = "agent_deleted"
        data: AgentID  # Or: agent_id: AgentID
        model_config = ConfigDict(extra="forbid")
    ```

    Or if you want to keep "data" as a nested object for consistency:
    ```python
    class AgentCreatedMsg(BaseModel):
        type: Literal["agent_created"] = "agent_created"
        agent_id: AgentID
        model_config = ConfigDict(extra="forbid")
    ```

    **Benefits:**
    1. Type safety: Can't accidentally pass non-agent IDs
    2. Self-documenting: AgentID clearly indicates what the string represents
    3. Refactoring safety: If AgentID changes, type checker catches issues
    4. Less code: No useless wrapper class
    5. Consistency: All agent IDs use the same type throughout codebase

    **Note:** If `AgentID` is a NewType (e.g., `AgentID = NewType('AgentID', str)`),
    Pydantic will handle it correctly. If it doesn't exist yet, it should be created
    in adgn/agent/types.py as `AgentID = NewType('AgentID', str)`.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/agents_ws.py': [
      [30, 30],  // AgentBrief.id: str (should be AgentID)
      [48, 50],  // AgentIdData class (useless wrapper, delete)
      [55, 55],  // AgentCreatedMsg.data: AgentIdData (should be AgentID)
      [61, 61],  // AgentDeletedMsg.data: AgentIdData (should be AgentID)
      [66, 66],  // AgentStatusData.id: str (should be AgentID)
    ],
  },
)
