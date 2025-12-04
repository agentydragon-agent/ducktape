local I = import '../../lib.libsonnet';

// Merged: test-bundles-five-subtests, test-bundles-four-plus-subtests,
// test-uses-loop-not-parametrize
// All describe test functions that bundle multiple independent test cases

I.issue(
  rationale= |||
    Test functions bundle multiple independent cases that should be split or parameterized.

    **Three forms:**

    1. Lines 355-476: 5 sequential subtests (text content, image content, error content,
       mixed, empty). Each creates CallToolResult, saves, retrieves, asserts independently.

    2. Lines 533-640: 4+ sequential subtests (corrupt JSON, missing field, non-existent
       call_id, malformed timestamp). Each manipulates database, asserts different errors.

    3. Lines 288-351: Loop iterating over 6 outcome scenarios (POLICY_ALLOW,
       POLICY_DENY_ABORT, USER_APPROVE, etc.).

    **Problems:**
    - If case N fails, cases N+1 never run
    - Can't identify which scenario failed from test name
    - Can't run individual cases via `pytest -k`
    - Violates pytest convention (one test = one thing)
    - No parallel execution even with pytest-xdist

    **Fix:** Split sequential subtests into separate functions with descriptive names
    (e.g., `test_calltoolresult_text_content`). For loops, use `@pytest.mark.parametrize`.
    Benefits: failure isolation, clear names, individual execution, parallel support.
  |||,
  filesToRanges={
    'adgn/tests/agent/persist/test_integration.py': [
      [355, 476],  // Five bundled subtests (CallToolResult content types)
      [533, 640],  // Four+ bundled subtests (error conditions)
      [288, 351],  // Loop over 6 outcome scenarios
    ],
  },
)
