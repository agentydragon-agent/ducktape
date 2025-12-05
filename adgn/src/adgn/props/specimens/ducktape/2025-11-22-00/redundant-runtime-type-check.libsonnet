local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Redundant runtime type check for parameter when type system already guarantees non-None.

    **Current code (container.py:34-35):**
    ```python
    def __init__(self, agent_id: AgentID, ...):
        if not agent_id:
            raise ValueError("ContainerPolicyEvaluator requires agent_id")
    ```

    The type annotation `agent_id: AgentID` (not `AgentID | None`) already guarantees
    the parameter is provided. This check adds defensive programming noise without value.

    **The correct approach:**

    Remove the check. The type system guarantees `agent_id` is present. If you need
    to validate empty strings, add validation to the `AgentID` type itself:

    ```python
    class AgentID(str):
        def __new__(cls, value: str):
            if not value:
                raise ValueError("AgentID cannot be empty")
            return super().__new__(cls, value)
    ```

    This centralizes validation at the type level, not at every usage site.

    **Benefits:**
    - Less code
    - Type system is the source of truth
    - No redundant checks at call sites
    - Validation happens once (at type construction)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [34, 35],  // Redundant if not agent_id check
    ],
  },
)
