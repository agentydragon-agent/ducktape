local I = import '../../specimens/lib.libsonnet';

// iss-021: created_at should auto-default to current time

I.issueOneOccurrence(
  rationale=|||
    SQLAlchemy models define created_at fields without default values (models.py:32,119,153):

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    This requires every creation site to manually pass created_at=datetime.now().

    SQLAlchemy supports automatic timestamps via server_default or default:

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now()  # Database-level default
    )

    Or Python-level default:
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC)  # Python-level default
    )

    Benefits:
    - DRY: timestamp logic in one place
    - Can't forget to set created_at
    - Consistent timestamp source
    - Less code at creation sites

    Affects: Agent, ToolCall, Policy models.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      32,           // Agent.created_at
      119,          // ToolCall.created_at
      153,          // Policy.created_at
    ],
  },
)
