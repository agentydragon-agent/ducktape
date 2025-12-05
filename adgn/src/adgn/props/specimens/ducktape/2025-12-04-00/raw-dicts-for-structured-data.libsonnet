local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Raw dicts are used to collect structured snapshot and issue data instead of using
    Pydantic models or dataclasses. This loses type safety and validation at construction time.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/db/sync.py': [[51, 54], [75, 80]]},
      note: 'In sync_snapshots_to_db: snapshot_data dict',
      expect_caught_from: [['adgn/src/adgn/props/db/sync.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/sync.py': [[179, 184], [229, 234]]},
      note: 'In sync_issues_to_db: issue_data and fp_data dicts',
      expect_caught_from: [['adgn/src/adgn/props/db/sync.py']],
    },
  ],
)
