local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Multiple uses of `with suppress(Exception):` to hide errors in tests that are meant
    to verify error handling behavior.

    **Current pattern (appears 5 times):**
    ```python
    with suppress(Exception):
        # Server attachment might fail; we're testing error handling
        requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
    ```

    **Why this is problematic:**
    If the test is meant to verify error handling, it should explicitly check for expected
    errors, not suppress all exceptions. Tests that suppress exceptions provide no signal
    when they fail - they just silently skip over problems.

    When an operation is expected to fail in a test:
    - Use `pytest.raises(SpecificException)` to verify the specific error occurs
    - Assert on the error message or error state
    - Don't hide failures with blanket suppression

    **Correct approach:**
    Remove `suppress(Exception)` calls. Either:
    1. Assert the operation succeeds (if it should)
    2. Assert the operation fails with specific exception (using pytest.raises)
    3. Verify the system handles the error appropriately (check error state, logs, etc.)

    Suppressing all exceptions makes the test unable to detect when something goes wrong.
  |||,
  filesToRanges={
    'adgn/tests/agent/e2e/test_mcp_errors.py': [
      [94, 96],
      [102, 103],
      [147, 148],
      [153, 155],
      [230, 232],
    ],
  },
)
