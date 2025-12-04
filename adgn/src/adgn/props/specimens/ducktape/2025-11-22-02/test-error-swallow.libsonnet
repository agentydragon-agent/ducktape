local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Tests use bare `except Exception:` blocks that swallow all errors, hiding real failures.

    Two pattern variations: `except Exception: break` in retry loops (lines 75-82 in
    test_mcp_concurrent.py) and `except Exception: pass` for optional operations (lines 171-175,
    251-255 in test_mcp_edge_cases.py).

    This hides actual errors during test execution. If operations fail for real reasons (element
    not found, page crashed, network failure, timeout), the test silently continues and may pass
    when it should fail.

    Remove try/except entirely if operation should succeed, or catch only specific expected
    exceptions (TimeoutError, ElementNotFoundError). Let real errors propagate. If approvals are
    optional, check conditions explicitly rather than swallowing all errors.
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
