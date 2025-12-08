local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Multiple SQL queries compare Snapshot.split using raw string literals ("train", "valid") instead of the Split enum (Split.TRAIN, Split.VALID). This bypasses type safety and makes typos harder to catch at static analysis time.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [230]},
      note: 'Compares db_snapshot.split == "valid" in validation',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [77]},
      note: 'Query with Snapshot.split == "train"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [138]},
      note: 'Where clause with Snapshot.split == "train"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [152]},
      note: 'Where clause with Snapshot.split == "train"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [225]},
      note: 'Where clause with Snapshot.split == "train"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [503]},
      note: 'Subquery with Snapshot.split == "valid"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [514]},
      note: 'Subquery with Snapshot.split == "valid"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/query_builders.py': [526]},
      note: 'Where clause with Snapshot.split == "valid"',
      expect_caught_from: [['adgn/src/adgn/props/db/query_builders.py']],
    },
  ],
)
