local I = import '../../lib.libsonnet';

// TokenRole + agent_id allows invalid state (AGENT role without agent_id)

I.issue(
  rationale=|||
    TokenRole + agent_id (mcp_routing.py:76-97) accepts role and agent_id
    separately, allowing invalid state (AGENT role without agent_id). Should
    use discriminated union (HumanTokenInfo | AgentTokenInfo) to make invalid
    state unrepresentable.

    Current code has runtime check `if not agent_id` at line 86 to handle
    the invalid state that the type system allows.

    Using discriminated union provides:
    - Type safety: invalid states unrepresentable
    - No runtime validation needed
    - Clear type contracts in signatures
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [[76, 97], 86],
  },
)
