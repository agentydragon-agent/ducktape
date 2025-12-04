local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/mcp/approval_policy/server.py'],
    ['adgn/src/adgn/agent/persist/__init__.py'],
  ],
  rationale=|||
    `ProposalDetail` (server.py:47-54) and `PolicyProposal` (persist/__init__.py:82-87) are
    duplicate models with identical fields: id, status, created_at, decided_at, content (5 fields,
    same types, same defaults, same semantics).

    Problems: (1) Identical definitions in two places. (2) Changes to proposal structure require
    updating both. (3) Violates DRY principle. (4) Creates confusion about which to use where.
    (5) PolicyProposal already defined in persistence layer (the right place).

    Fix: Delete ProposalDetail from server.py, import PolicyProposal from adgn.agent.persist,
    replace uses: proposal_detail function return type (line 163) and construction (lines 168-174).

    Benefits: Single source of truth, eliminates 8 lines of duplication, clearer type hierarchy
    (persistence types used by API layer), changes happen in one place, consistent with how other
    persistence types are reused.

    Note: ProposalDescriptor (server.py:40-44) is different - lightweight descriptor WITHOUT
    content field, should remain separate.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/approval_policy/server.py': [
      [47, 54],    // ProposalDetail duplicate type definition
      [163, 174],  // ProposalDetail usage (return type and construction)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [82, 87],    // PolicyProposal original type definition
    ],
  },
)
