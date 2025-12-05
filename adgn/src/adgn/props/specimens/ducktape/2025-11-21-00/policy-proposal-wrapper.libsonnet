local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/agent/persist/__init__.py'],
  ],
  rationale=|||
    Lines 171-178 define `PolicyProposalInfo` with fields `id`, `status`, `created_at`, `decided_at`,
    and `proposal_uri`. Lines 464-473 convert `PolicyProposal` objects from persistence (persist/__init__.py:82-87,
    5 fields including `content`) to `PolicyProposalInfo`, copying 4 fields and adding computed
    `proposal_uri` via f-string.

    This is unnecessary indirection: `PolicyProposalInfo` is just `PolicyProposal` minus `content`
    field plus computable URI. Creates two types representing proposals (persistence vs API), requires
    manual conversion copying fields, and manual URI construction with f-string.

    Delete `PolicyProposalInfo` class (lines 171-178) and return `list[PolicyProposal]` directly from
    `agent_policy_proposals()`. Update `AgentPolicyProposals.proposals` type from `list[PolicyProposalInfo]`
    to `list[PolicyProposal]`. Eliminates wrapper, conversion loop (lines 464-473), and establishes
    single source of truth.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [171, 178],  // PolicyProposalInfo unnecessary wrapper type
      [464, 473],  // Conversion from PolicyProposal to PolicyProposalInfo
      [470, 470],  // Manual URI construction
      [475, 477],  // Usage in return statement
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [82, 87],    // PolicyProposal original type for reference
    ],
  },
)
