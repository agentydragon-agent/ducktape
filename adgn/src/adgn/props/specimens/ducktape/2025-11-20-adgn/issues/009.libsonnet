local I = import '../../specimens/lib.libsonnet';

// iss-009: Policy model docstring duplicates PolicyStatus enum documentation

I.issueOneOccurrence(
  rationale=|||
    Policy model has a docstring (models.py:135-145) that documents the status states:
    - ACTIVE: Currently active policy
    - PROPOSED: Awaiting approval
    - REJECTED: Proposal was rejected
    - SUPERSEDED: Was active, replaced by newer policy

    This duplicates information that should only exist on PolicyStatus StrEnum
    (defined in persist/__init__.py).

    The docstring also mentions "Only ONE policy per agent can be ACTIVE at a time"
    which is a database constraint, not a model documentation concern.

    Model docstrings should describe the model's purpose, not enumerate enum values
    or explain database constraints. Enum documentation belongs on the enum definition.

    Fix:
    - Remove state enumeration from Policy docstring
    - Keep only: "Per-agent approval policy with status tracking."
    - Full state documentation lives on PolicyStatus enum
    - Database constraint documented via __table_args__ comment if needed
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      [135, 145],   // Policy docstring with duplicated enum values
    ],
  },
)
