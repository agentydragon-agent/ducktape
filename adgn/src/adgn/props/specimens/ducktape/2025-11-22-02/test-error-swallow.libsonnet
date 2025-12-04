local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Tests swallow all exceptions with bare `except Exception:` blocks, hiding real errors.

    **Pattern variations:**
    ```python
    # Variant 1: except Exception: break
    for _ in range(15):
        try:
            approve_btn = page.get_by_role("button", name="Approve").first
            if approve_btn.count() > 0:
                approve_btn.click()
                page.wait_for_timeout(100)
        except Exception:
            break

    # Variant 2: except Exception: pass
    try:
        wait_for_pending_approvals(page, count=1, timeout=5000)
        approve_first_pending(page)
    except Exception:
        pass  # No approval needed
    ```

    **Why this is problematic:**
    This hides actual errors that might occur during test execution. If operations fail
    for real reasons (element not found, page crashed, network failure, timeout), the
    test silently continues and may pass when it should fail.

    **Correct approach:**
    - Remove try/except entirely if operation should succeed
    - Catch only specific expected exceptions (e.g., TimeoutError, ElementNotFoundError)
    - Let real errors propagate to fail the test
    - If approvals are optional, explicitly check conditions rather than swallowing all errors
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_concurrent.py': [[75, 82]],
      },
      note: 'Error-swallowing in approval loop with `except Exception: break`',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_concurrent.py']],
    },
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_edge_cases.py': [
          [171, 175],
          [251, 255],
        ],
      },
      note: 'Error-swallowing in optional approval checks with `except Exception: pass`',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_edge_cases.py']],
    },
  ],
)
