local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    SQLAlchemy models define created_at fields without default values, requiring every
    creation site to manually pass created_at=datetime.now(). SQLAlchemy supports automatic
    timestamps via server_default=func.now() or default=lambda: datetime.now(UTC).

    Benefits of auto-defaults:
    - DRY: timestamp logic in one place
    - Can't forget to set created_at
    - Consistent timestamp source
    - Less code at creation sites
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/persist/models.py': [32],
      },
      note: 'Agent.created_at field',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/persist/models.py': [119],
      },
      note: 'ToolCall.created_at field',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/persist/models.py': [153],
      },
      note: 'Policy.created_at field',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
  ],
)
