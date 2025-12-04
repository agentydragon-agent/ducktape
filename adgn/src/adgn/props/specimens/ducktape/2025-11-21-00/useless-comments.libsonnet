local I = import '../../lib.libsonnet';

// Merged: create-agent-useless-comments, misleading-required-comments
// Both describe comments that add no value (obvious or misleading)

I.issue(
  snapshot='ducktape/2025-11-21-00',
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/agent/persist/__init__.py'],
  ],
  rationale= |||
    Multiple locations have comments that add no value: either restating obvious
    code operations or providing misleading/incorrect information about field requirements.

    **Pattern 1: Comments restating obvious code** (agents.py:785-792):
    ```python
    # Generate unique agent ID
    agent_id = AgentID(f"agent-{uuid4().hex[:8]}")

    # Create infrastructure for the agent
    await registry.create_agent(agent_id)

    # Return agent brief with the created agent's ID
    return AgentBrief(id=agent_id)
    ```

    Problems:
    - Each comment just restates what the code does
    - Function already has comprehensive docstring
    - Empty lines between simple statements add no value

    **Pattern 2: Misleading "All fields are REQUIRED" comments** (persist/__init__.py):
    ```python
    class Decision(BaseModel):
        """Decision made about a tool call.

        All fields are REQUIRED. The entire Decision object is optional on ToolCallRecord.
        """
        outcome: ApprovalOutcome
        decided_at: datetime
        reason: str | None = None
    ```

    Problems:
    - Comment claims "All fields are REQUIRED" but `reason` has a default (optional)
    - In Pydantic, fields without defaults are required by definition
    - Comment contradicts the code

    Similar issue in ToolCallExecution and agent_id field comments.

    **Why these are problematic:**
    - **Noise**: Make code harder to scan without adding information
    - **Maintenance burden**: Must be kept in sync as code changes
    - **Misleading**: Some comments are factually incorrect
    - **Redundant**: Code and type annotations already convey the information

    **Recommended fix:**
    Remove all these comments. For simple operations, the code is self-documenting.
    For Pydantic models, type annotations define requirements.

    **Benefits:**
    - More concise code
    - No risk of comments becoming outdated/incorrect
    - Trusts reader to understand simple operations
    - Follows principle: comments should explain WHY, not WHAT
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [785, 792],  // Function body with useless comments and empty lines
      [785, 785],  // Comment: "Generate unique agent ID"
      [787, 787],  // Empty line
      [788, 788],  // Comment: "Create infrastructure for the agent"
      [790, 790],  // Empty line
      [791, 791],  // Comment: "Return agent brief with the created agent's ID"
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [90, 98],    // Decision class with misleading "All fields are REQUIRED" comment
      [93, 93],    // Line with incorrect comment
      [101, 109],  // ToolCallExecution class with misleading "All fields are REQUIRED" comment
      [104, 104],  // Line with redundant comment
      [123, 123],  // agent_id with redundant "# REQUIRED" inline comment
    ],
  },
)
