local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    TOKEN_TABLE uses nested untyped dicts (mcp_routing.py:37-40):

    TOKEN_TABLE: dict[str, dict[str, str]] = {
        "human-token-123": {"role": "human"},
        "agent-token-abc": {"role": "agent", "agent_id": "agent-1"},
    }

    Problems:
    - No type safety: can't validate field presence
    - No autocomplete for fields (role, agent_id)
    - Field names are magic strings
    - Can't distinguish required vs optional fields
    - Code accesses with dict["role"], dict.get("agent_id")

    Should define Pydantic model:
    class TokenInfo(BaseModel):
        role: TokenRole  # Already a StrEnum
        agent_id: AgentID | None = None

    TOKEN_TABLE: dict[str, TokenInfo] = {
        "human-token-123": TokenInfo(role=TokenRole.HUMAN),
        "agent-token-abc": TokenInfo(role=TokenRole.AGENT, agent_id="agent-1"),
    }

    Benefits:
    - Type safety: token_info.role, token_info.agent_id
    - Validation: can't create invalid TokenInfo
    - Clear schema: required role, optional agent_id
    - IDE support: autocomplete and type checking

    Code already uses TokenRole enum, should extend to full typed model.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [37, 40],     // TOKEN_TABLE definition
      115,          // token_info["role"] access
      116,          // token_info.get("agent_id") access
    ],
  },
)
