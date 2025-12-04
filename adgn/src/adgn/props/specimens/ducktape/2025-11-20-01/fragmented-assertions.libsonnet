local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Tests use multiple separate assertions instead of structured matchers (hamcrest or Pydantic model equality).

    Benefits of structured matchers:
    - Single assertion with clear expected structure
    - Better error messages showing which specific property failed or full diff
    - Less verbose code
    - More explicit about intent
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/agent/test_runtime_timeout.py': [[38, 40]],
      },
      note: 'Multiple separate assertions for object properties (instance type, exit_code, stdout); should use has_properties',
      expect_caught_from: [['adgn/tests/agent/test_runtime_timeout.py']],
    },
    {
      files: {
        'adgn/tests/agent/test_policy_validation_reload.py': [[62, 63], [77, 79]],
      },
      note: 'Multiple assertions to check error messages (length > 0, then substring); should use has_item(contains_string(...))',
      expect_caught_from: [['adgn/tests/agent/test_policy_validation_reload.py']],
    },
    {
      files: {
        'adgn/tests/mcp/approval_policy/test_policy_resources.py': [[171, 176], [213, 218], [249, 252], [289, 290], [308, 309], [320, 321]],
      },
      note: 'Individual field assertions instead of structured comparison; should use Pydantic model equality or has_properties',
      expect_caught_from: [['adgn/tests/mcp/approval_policy/test_policy_resources.py']],
    },
  ],
)
