local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/models/proposal_status.py'], ['adgn/src/adgn/agent/persist/__init__.py'], ['adgn/src/adgn/agent/persist/models.py'], ['adgn/src/adgn/agent/persist/sqlite.py'], ['adgn/src/adgn/agent/mcp_bridge/servers/approval_policy_bridge.py']],
  rationale=|||
    Two enums exist for policy status: PolicyStatus (persist/__init__.py:54-58, models.py:39-43)
    and ProposalStatus (models/proposal_status.py:6-10). The codebase mixes them inconsistently.

    PolicyStatus has ACTIVE, SUPERSEDED, PROPOSED, REJECTED. ProposalStatus has PENDING,
    APPROVED, REJECTED, ERROR.

    sqlite.py mismatches types: creates with ProposalStatus.PENDING (line 217), filters with
    ProposalStatus values (231), approves with PolicyStatus.ACTIVE (283), rejects with
    ProposalStatus.REJECTED (293). Works at runtime because StrEnum values are strings, but
    type checker can't catch the mixing.

    Line 76 in approval_policy_bridge.py converts PolicyStatus → ProposalStatus when building
    ProposalDescriptor, masking the mismatch.

    Problems: type confusion (same concept, two incompatible types), lost type safety,
    semantic mismatch (PENDING vs PROPOSED, APPROVED vs ACTIVE), dead code
    (ProposalStatus.APPROVED never set), maintenance burden.

    Fix: unify into single enum in shared location with all lifecycle states (PENDING, ACTIVE,
    SUPERSEDED, REJECTED, ERROR). Remove duplicates and runtime conversion. String values
    remain compatible (no DB migration needed).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/proposal_status.py': [
      [6, 10],   // ProposalStatus enum definition (should be removed/unified)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [54, 58],  // PolicyStatus enum definition (duplicate)
    ],
    'adgn/src/adgn/agent/persist/models.py': [
      [39, 43],  // PolicyStatus enum definition (duplicate, comment says "avoid circular imports")
      [176, 176], // Policy.status typed as PolicyStatus
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [217, 217], // Creates with ProposalStatus.PENDING (wrong type)
      [231, 231], // Filters with ProposalStatus values (wrong type, includes APPROVED which is never set!)
      [283, 283], // Approves with PolicyStatus.ACTIVE (correct)
      [293, 293], // Rejects with ProposalStatus.REJECTED (wrong type)
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/approval_policy_bridge.py': [
      [12, 12],  // Imports ProposalStatus
      [76, 76],  // Runtime conversion ProposalStatus(p.status) masks type mismatch
    ],
  },
)
