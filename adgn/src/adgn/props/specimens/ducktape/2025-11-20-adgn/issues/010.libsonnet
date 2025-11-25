local I = import '../../specimens/lib.libsonnet';

// iss-010: Policy.status should use PolicyStatus StrEnum type

I.issueOneOccurrence(
  rationale=|||
    Policy model declares status field as Mapped[str] with comment indicating it should
    be PolicyStatus enum (models.py:152).

    Current: status: Mapped[str] = mapped_column(String, nullable=False)
    Comment says: # active|proposed|rejected|superseded (PolicyStatus)

    SQLAlchemy 2.0+ supports native Python Enum mapping. Should use:
    status: Mapped[PolicyStatus] = mapped_column(nullable=False)

    Benefits:
    - Type safety: can't assign arbitrary strings
    - IDE autocomplete for valid status values
    - Runtime validation (can't save invalid status)
    - No need for inline comment listing values
    - Consistency with PolicyStatus enum definition

    SQLAlchemy automatically maps Python enums to VARCHAR/String columns while
    preserving enum type semantics in Python code.

    Same pattern should apply to any other fields using string with comment
    listing valid values.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      152,          // status: Mapped[str] with PolicyStatus comment
    ],
  },
)
