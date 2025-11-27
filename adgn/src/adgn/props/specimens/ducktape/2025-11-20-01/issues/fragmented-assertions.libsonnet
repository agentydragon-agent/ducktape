local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Tests use multiple separate assertions instead of structured matchers (hamcrest or Pydantic model equality).

    Three patterns of fragmented assertions:

    1. Multiple separate assertions for object properties (test_runtime_timeout.py lines 38-40):
       - Separate `assert_that` for instance type
       - Separate `assert` for exit_code
       - Separate `assert` for stdout
       Should use `has_properties` to check all attributes in one assertion.

    2. Multiple assertions to check error messages (test_policy_validation_reload.py lines 62-63, 77-79):
       - First checks length > 0
       - Second checks substring in first error
       Should use single hamcrest check: `assert_that(result.errors, has_item(contains_string("...")))`

    3. Individual field assertions instead of structured comparison (test_policy_resources.py multiple locations):
       - Multiple separate `assert` statements checking `policy.id`, `policy.text`, `policy.description`, `policy.enabled`
       Should use either:
         - Pydantic model equality: `assert policy == Policy(...)`
         - Hamcrest `has_properties`: `assert_that(policy, has_properties(...))`

    Benefits of structured matchers:
    - Single assertion with clear expected structure
    - Better error messages showing which specific property failed or full diff
    - Less verbose code
    - More explicit about intent
  |||,
  filesToRanges={
    'adgn/tests/agent/test_runtime_timeout.py': [[38, 40]],
    'adgn/tests/agent/test_policy_validation_reload.py': [
      [62, 63],
      [77, 79],
    ],
    'adgn/tests/mcp/approval_policy/test_policy_resources.py': [
      [171, 176],
      [213, 218],
      [249, 252],
      [289, 290],
      [308, 309],
      [320, 321],
    ],
  },
)
