local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Lines 44-55 and 288-298 in test_mcp_errors.py check for unimplemented UI error elements
    (.error, .alert-error, [data-testid='error-message']) with fallback logic that accepts
    completely different behaviors (WS connection status).

    Three problems: tests unimplemented features (backend no longer implements those error UI
    elements); swallows all errors with bare `except Exception:` hiding actual test failures;
    accepts contradictory outcomes (either error indicators appear OR WS disconnects - having
    both as acceptable makes tests meaningless, they pass regardless of what happens).

    Tests should NOT have fallback logic accepting massively different behaviors. Pick ONE
    expected behavior per test and assert it happens. Remove tests for unimplemented UI features
    or implement the features first. Remove error-swallowing exception handlers. If testing error
    states, verify the specific error indicator that actually exists.
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
