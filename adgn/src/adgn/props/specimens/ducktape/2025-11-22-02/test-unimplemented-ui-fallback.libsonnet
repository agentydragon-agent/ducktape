local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Tests check for unimplemented UI features with error-swallowing fallback logic that
    accepts completely different behaviors, making the tests meaningless.

    **Current pattern (lines 44-55):**
    ```python
    try:
        # Wait for either an error message or connection failure indicator
        error_indicator = page.locator(".error, .alert-error, [data-testid='error-message']").first
        error_indicator.wait_for(state="visible", timeout=5000)
        # Verify error text mentions the problem
        error_text = error_indicator.inner_text()
        assert_that(error_text, has_length(greater_than(0)), "Error message should not be empty")
    except Exception:
        # Alternative: check if WS connection shows as disconnected/failed
        ws_status = page.locator(".ws .dot")
        # Should not show "on" (connected) state
        ws_status.wait_for(timeout=5000)
    ```

    **Three problems:**
    1. **Tests unimplemented features**: The backend no longer implements the error UI
       elements (.error, .alert-error, [data-testid='error-message']) that this checks for
    2. **Swallows all errors**: Bare `except Exception:` hides actual test failures
    3. **Accepts contradictory outcomes**: Tests should NOT have fallback logic accepting
       massively different behaviors. Either error indicators should appear OR the WS
       connection should disconnect - pick ONE expected behavior. Having both as acceptable
       makes the test meaningless (it passes regardless of what happens).

    **Correct approach:**
    1. Remove tests for unimplemented UI features, or implement the features first
    2. Pick ONE expected behavior per test and assert it happens
    3. Remove error-swallowing exception handlers
    4. If testing error states, verify the specific error indicator that actually exists
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_errors.py': [
          [44, 55],
          [288, 298],
        ],
      },
      note: 'Two instances with unimplemented UI element checks and contradictory fallback logic',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_errors.py']],
    },
  ],
)
