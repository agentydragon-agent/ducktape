local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    The pattern of creating stateful mock response handlers (a dict with `{"i": 0}` and an
    `async def responses_create(_req)` function that increments the counter and returns
    tool calls from a sequence) is duplicated 16+ times across the test suite.

    **Why this is problematic:**
    - 40+ lines of duplicated code across test suite
    - Each occurrence is essentially identical with minor variations
    - Changes to the pattern must be replicated everywhere
    - Increases maintenance burden and risk of inconsistency

    **Fix:** Extract into a shared `make_stateful_responses(responses_factory, response_sequence)`
    helper in conftest.py or tests/agent/helpers.py that takes a list of (function_name,
    server_name, params) tuples and returns the stateful handler. This eliminates duplication
    across all 16+ instances.
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_concurrent.py': [
          [100, 110],
          [159, 169],
          [269, 283],
        ],
      },
      note: 'Three instances in test_mcp_concurrent.py',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_concurrent.py']],
    },
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_errors.py': [
          [73, 82],
          [127, 135],
          [184, 193],
          [249, 256],
        ],
      },
      note: 'Four instances in test_mcp_errors.py',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_errors.py']],
    },
    {
      files: {
        'adgn/tests/agent/e2e/test_mcp_edge_cases.py': [
          [38, 51],
          [100, 101],
          [139, 152],
          [207, 220],
          [275, 283],
        ],
      },
      note: 'Five instances in test_mcp_edge_cases.py',
      expect_caught_from: [['adgn/tests/agent/e2e/test_mcp_edge_cases.py']],
    },
  ],
)
