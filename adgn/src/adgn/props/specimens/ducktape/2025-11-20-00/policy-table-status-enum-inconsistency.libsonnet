local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The Policy table's status column is written with values from two different enums inconsistently:
    approve_policy_proposal (lines 303-308) writes PolicyStatus.ACTIVE and PolicyStatus.SUPERSEDED,
    while reject_policy_proposal (line 321) writes ProposalStatus.REJECTED. This means the same
    database column holds a mix of enum values from different types, making queries fragile and
    prone to type errors when instantiating Pydantic models (e.g., PolicyProposal expects
    ProposalStatus but may receive PolicyStatus values). These should be merged into a single enum
    representing all policy states (active, superseded, pending, approved, rejected) for a unified
    policy table that tracks both proposals and active policies. Additionally, the enum could be
    linked to the ORM using SQLAlchemy's Enum type (which creates a SQL-level CHECK constraint or
    native enum type) to prevent storing invalid status values and catch misuse at the API boundary.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [[303, 308], [321, 321]],
  },
)
