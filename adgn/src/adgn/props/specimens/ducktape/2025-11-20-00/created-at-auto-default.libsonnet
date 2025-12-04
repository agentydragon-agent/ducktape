local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale= |||
    SQLAlchemy models define created_at fields without default values, requiring every
    creation site to manually pass created_at=datetime.now(). SQLAlchemy supports automatic
    timestamps via server_default=func.now() or default=lambda: datetime.now(UTC).

    Benefits of auto-defaults:
    - DRY: timestamp logic in one place
    - Can't forget to set created_at
    - Consistent timestamp source
    - Less code at creation sites

    Affects: Agent, ToolCall, Policy models (all at models.py lines 32, 119, 153).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      32,   // Agent.created_at
      119,  // ToolCall.created_at
      153,  // Policy.created_at
    ],
  },
)
