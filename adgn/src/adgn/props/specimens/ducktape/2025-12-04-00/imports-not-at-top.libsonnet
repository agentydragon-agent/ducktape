local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Imports not at module top. Per project conventions, all imports should be at module top unless they break a circular dependency (in which case they require a one-line comment explaining the cycle).
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/db/models.py': [[8, 8]]},
      note: 'Conditional import for type checking inside function body instead of at module top',
      expect_caught_from: [['adgn/src/adgn/props/db/models.py']],
    },
    {
      files: {'adgn/tests/props/conftest.py': [[1, 15]]},
      note: 'Missing DatabaseConfig import at module top',
      expect_caught_from: [['adgn/tests/props/conftest.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/models.py': [[20, 22]]},
      note: 'TYPE_CHECKING conditional import below normal imports instead of at module top',
      expect_caught_from: [['adgn/src/adgn/props/grader/models.py']],
    },
  ],
)
