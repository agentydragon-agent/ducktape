local I = import '../../specimens/lib.libsonnet';

// iss-015: Run.status and Event.type should use StrEnum types

I.issueOneOccurrence(
  rationale=|||
    SQLAlchemy models use Mapped[str] with comments indicating enum types, but don't
    use the actual enum types.

    Run.status (models.py:61): Mapped[str] with comment "RunStatus enum value"
    Event.type (models.py:90): Mapped[str] with comment "EventType enum value"

    Both RunStatus (server/protocol.py:80) and EventType (persist/__init__.py:54)
    are defined as StrEnum.

    SQLAlchemy 2.0+ supports native Python Enum mapping. Should use:
    status: Mapped[RunStatus] = mapped_column(nullable=False)
    type: Mapped[EventType] = mapped_column(nullable=False)

    Benefits:
    - Type safety: can't assign arbitrary strings
    - IDE autocomplete for valid values
    - Runtime validation (can't save invalid status/type)
    - No need for inline comments listing values
    - Consistency with enum definitions

    Same pattern as issue 010 (Policy.status).
  |||,
  properties=['python/strenum', 'type-correctness-and-specificity', 'structured-data-over-untyped-mappings'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      61,           // Run.status: Mapped[str] with RunStatus comment
      90,           // Event.type: Mapped[str] with EventType comment
    ],
  },
)
