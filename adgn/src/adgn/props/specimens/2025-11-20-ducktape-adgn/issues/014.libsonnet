local I = import '../../specimens/lib.libsonnet';

// iss-014: proposal_id parameters should be int not str

I.issueOneOccurrence(
  rationale=|||
    Policy.id is defined as Mapped[int] (models.py:149), but all APIs accept
    proposal_id: str and convert with try/except int(proposal_id) at runtime.

    Current pattern (sqlite.py:280-289):
    async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int:
        try:
            policy_id = int(proposal_id)
        except ValueError:
            raise KeyError("proposal_not_found")

    Should accept int directly:
    async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: int) -> int:
        # Use policy_id directly, no conversion

    Affects 9+ locations across protocol definitions, implementations, and MCP tools.
    All have identical try/except ValueError conversion logic.

    Benefits:
    - Type correctness: matches database column type
    - No runtime conversion overhead
    - No ValueError handling needed
    - Clear type contract in signatures
  |||,
  properties=['type-correctness-and-specificity', 'no-defensive-programming'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/__init__.py': [
      202,          // create_policy_proposal proposal_id: str return type
      204,          // get_policy_proposal proposal_id: str
      205,          // approve_policy_proposal proposal_id: str
      206,          // reject_policy_proposal proposal_id: str
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      223,          // create_policy_proposal with int(proposal_id)
      259,          // get_policy_proposal with int(proposal_id)
      [280, 289],   // approve_policy_proposal with int(proposal_id)
      [311, 321],   // reject_policy_proposal with int(proposal_id)
    ],
    'adgn/src/adgn/agent/approvals.py': [
      211,          // create_proposal proposal_id: str
      237,          // approve_proposal proposal_id: str
      254,          // reject_proposal proposal_id: str
    ],
    'adgn/src/adgn/agent/mcp/servers/agents.py': [
      747,          // approve_policy_proposal_tool proposal_id: str
    ],
    'adgn/src/adgn/agent/web/resources.py': [
      67,           // approve_policy_proposal proposal_id: str
    ],
  },
)
