local I = import '../../specimens/lib.libsonnet';

// iss-041: Role and agent_id should be disjoint union to prevent invalid states

I.issueOneOccurrence(
  rationale=|||
    _get_backend_app accepts role and agent_id separately, creating invalid state:
    "agent role without agent_id" (mcp_routing.py:76-97).

    Current signature:
    async def _get_backend_app(self, role: TokenRole, agent_id: str | None) -> ASGIApp:
        if role == TokenRole.HUMAN:
            backend_key = "human"
            # ... no agent_id needed
        if role == TokenRole.AGENT:
            if not agent_id:
                raise ValueError("Agent role requires agent_id")  # Runtime check!
            backend_key = f"agent:{agent_id}"
            # ... uses agent_id

    Problem: The type system allows TokenRole.AGENT with agent_id=None, which is
    invalid. Requires runtime ValueError check.

    This relates to issue 030 (TOKEN_TABLE should use Pydantic). The root cause
    is that TokenInfo should be a tagged union, not flat dict.

    Should define disjoint union:
    class HumanTokenInfo(BaseModel):
        role: Literal[TokenRole.HUMAN]
        # No agent_id field

    class AgentTokenInfo(BaseModel):
        role: Literal[TokenRole.AGENT]
        agent_id: AgentID  # Required, not optional

    TokenInfo = HumanTokenInfo | AgentTokenInfo

    Then signature becomes:
    async def _get_backend_app(self, token_info: TokenInfo) -> ASGIApp:
        match token_info:
            case HumanTokenInfo():
                backend_key = "human"
                # ...
            case AgentTokenInfo(agent_id=agent_id):
                backend_key = f"agent:{agent_id}"
                # ...

    Benefits:
    - Invalid state unrepresentable: can't have agent without agent_id
    - No runtime ValueError check needed
    - Type-safe pattern matching
    - Clearer intent: two distinct token types
    - Exhaustiveness checking via match

    This is "parse, don't validate" principle: use types to prevent invalid states.
  |||,
  properties=['type-correctness-and-specificity', 'invalid-state-unrepresentable', 'no-defensive-programming'],
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [76, 97],     // _get_backend_app with role+agent_id parameters
      86,           // Runtime check: if not agent_id
    ],
  },
  gap_note=|||
    Requires refactoring TOKEN_TABLE (issue 030) to use tagged union TokenInfo.
    Then propagate typed TokenInfo through dispatch method.
  |||,
)
