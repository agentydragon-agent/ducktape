local I = import '../../specimens/lib.libsonnet';

// ID fields use inconsistent types (str vs domain types). Should use domain types throughout.

I.issueOneOccurrence(
  rationale= |||
    Multiple ID fields use raw str types instead of domain-specific ID types, losing
    type safety and semantic meaning:

    1. Agent.id (models.py:70): Mapped[str], but code wraps with AgentID() at runtime
       (sqlite.py:131,147). If SQLAlchemy supports NewType, should declare as AgentID
       to eliminate runtime wrappers.

    2. AgentSession.agent_id (runtime.py:234,251): Uses str | None, but AgentID is
       the semantic identifier type used throughout codebase.

    3. Policy proposal_id (models.py:149): Database column is int, but all APIs
       accept str and convert with try/except int() at runtime. 13 locations have
       identical conversion logic.

    4. Run.id (models.py:57): Mapped[str] in model, but domain code uses UUID.
       Creates constant str(run_id) conversions (sqlite.py:378,389). SQLAlchemy
       supports UUID types that handle serialization automatically.

    5. TokenRole + agent_id (mcp_routing.py:76-97): Accepts role and agent_id
       separately, allowing invalid state (AGENT role without agent_id). Should
       use discriminated union (HumanTokenInfo | AgentTokenInfo) to make invalid
       state unrepresentable.

    Using domain types provides:
    - Type safety: can't mix different ID types
    - Semantic clarity: not just any string/int, but specific identifier
    - No runtime conversions/validation
    - Clear type contracts in signatures
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      57,           // Run.id: Mapped[str] (should be UUID)
      70,           // Agent.id: Mapped[str] (should be AgentID)
      149,          // Policy.id: Mapped[int]
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      131,          // id=AgentID(agent.id)
      147,          // id=AgentID(agent.id)
      223,          // create_policy_proposal with int(proposal_id)
      259,          // get_policy_proposal with int(proposal_id)
      [280, 289],   // approve_policy_proposal with int(proposal_id)
      [311, 321],   // reject_policy_proposal with int(proposal_id)
      378,          // Event creation: run_id=str(run_id)
      389,          // WHERE Run.id == str(run_id)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      202,          // create_policy_proposal proposal_id: str return type
      204,          // get_policy_proposal proposal_id: str
      205,          // approve_policy_proposal proposal_id: str
      206,          // reject_policy_proposal proposal_id: str
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      234,          // agent_id: str | None parameter
      251,          // self.agent_id: str | None field
    ],
    'adgn/src/adgn/agent/approvals.py': [
      211,          // create_proposal proposal_id: str
      237,          // approve_proposal proposal_id: str
      254,          // reject_proposal proposal_id: str
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      747,          // approve_policy_proposal_tool proposal_id: str
    ],
    'adgn/src/adgn/agent/mcp_bridge/resources.py': [
      67,           // approve_policy_proposal proposal_id: str
    ],
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [76, 97],     // _get_backend_app with role+agent_id parameters
      86,           // Runtime check: if not agent_id
    ],
  }
)
