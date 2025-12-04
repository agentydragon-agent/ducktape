local I = import '../../lib.libsonnet';

// Merged: test-bundles-five-subtests, test-bundles-four-plus-subtests,
// test-uses-loop-not-parametrize
// All describe test functions that bundle multiple independent test cases

I.issue(
  snapshot='ducktape/2025-11-22-01',
  rationale= |||
    Test functions bundle multiple independent test cases that should be split into
    separate test functions or parameterized.

    **Pattern: Multiple test cases in one function**

    This anti-pattern appears in three forms:

    **1. Five sequential subtests (lines 355-476)**
    Test function with 5 independent subtests marked by comments:
    - Test 1: Text content
    - Test 2: Image content
    - Test 3: Error content
    - Test 4: Mixed content (text + image)
    - Test 5: Empty content (edge case)

    Each creates a CallToolResult record, saves, retrieves, and asserts independently.

    **2. Four+ sequential subtests (lines 533-640)**
    Test function with 4+ independent subtests marked by comments:
    - Test 1: Manually corrupt the JSON in the database
    - Test 2: Insert record with missing required field in JSON
    - Test 3: Get non-existent call_id (should return None, not raise)
    - Test 4: Test with malformed timestamp

    Each manipulates the database independently and asserts different error conditions.

    **3. Loop over test cases (lines 288-351)**
    Test function uses enumerate loop to iterate over 6 outcome scenarios:
    POLICY_ALLOW, POLICY_DENY_ABORT, USER_APPROVE, etc.

    **Problems with bundled test cases:**
    - Poor failure reporting: If case N fails, cases N+1 onward never run
    - Unclear test names: Can't identify which scenario failed without reading output
    - Can't run individually: No way to run just one case via pytest `-k`
    - Violates pytest conventions: One test function should test one thing
    - No parallel execution: All cases run sequentially even with pytest-xdist

    **Correct approach:**

    **For sequential subtests:** Split into separate test functions with descriptive names.

    Example from case 1:
    ```python
    def test_calltoolresult_text_content(): ...
    def test_calltoolresult_image_content(): ...
    def test_calltoolresult_error_content(): ...
    def test_calltoolresult_mixed_content(): ...
    def test_calltoolresult_empty_content(): ...
    ```

    **For loop-based cases:** Use `@pytest.mark.parametrize`:

    Example from case 3:
    ```python
    @pytest.mark.parametrize("outcome,execution,reason", [
        (POLICY_ALLOW, True, None),
        (POLICY_DENY_ABORT, False, "policy"),
        (USER_APPROVE, True, None),
        # ... 6 cases total
    ])
    def test_tool_call_outcome(outcome, execution, reason):
        # Test body here
    ```

    **Benefits:**
    - Each case runs independently (failure isolation)
    - Clear test names in pytest output
    - Can run individual cases: `pytest -k "test_text_content"`
    - Parallel execution with pytest-xdist
    - IDE test runners show each case separately
  |||,
  filesToRanges={
    'adgn/tests/agent/persist/test_integration.py': [
      [355, 476],  // Five bundled subtests (CallToolResult content types)
      [533, 640],  // Four+ bundled subtests (error conditions)
      [288, 351],  // Loop over 6 outcome scenarios
    ],
  },
)
