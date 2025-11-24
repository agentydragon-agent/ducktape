local I = import '../../specimens/lib.libsonnet';

// iss-044: ApprovalPolicyInfo has mutable field default

I.issueOneOccurrence(
  rationale=|||
    ApprovalPolicyInfo uses mutable list as default (protocol.py:75):

    class ApprovalPolicyInfo(BaseModel):
        content: str
        id: int
        proposals: list[ProposalInfo] = []

    This creates a shared mutable default across all instances without explicit value.

    While Pydantic >= 2.0 handles this safely (creates new list per instance), it's
    still a code smell that:
    1. Looks like classic Python mutable default bug
    2. Requires knowing Pydantic internals to understand safety
    3. Inconsistent with Python best practices

    Should use Pydantic's default_factory or Field with default_factory:

    proposals: list[ProposalInfo] = Field(default_factory=list)

    Or for newer Pydantic:
    proposals: list[ProposalInfo] = []  # Pydantic 2.0+ handles this safely

    But Field(default_factory=list) is:
    - More explicit about intent
    - Clearer for readers unfamiliar with Pydantic 2.0 changes
    - Matches documentation best practices
    - Future-proof if model converted to dataclass

    Same pattern should apply to any mutable defaults (dict, set, etc).
  |||,
  properties=['python/mutable-defaults'],
  filesToRanges={
    'adgn/src/adgn/agent/server/protocol.py': [
      75,           // proposals: list[ProposalInfo] = []
    ],
  },
  gap_note=|||
    Check Pydantic version in use. If Pydantic 1.x, this IS a bug that causes
    shared state. If Pydantic 2.x, it works but should use Field(default_factory=list)
    for clarity.
  |||,
)
