local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    The pattern of creating stateful mock response handlers is duplicated 16+ times across
    the test suite, appearing in at least 15 test files.

    **Pattern (repeated):**
    ```python
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "first call"}, call_id="call_echo_1"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")
    ```

    **Why this is problematic:**
    - 40+ lines of duplicated code across test suite
    - Each occurrence is essentially identical with minor variations
    - Changes to the pattern must be replicated everywhere
    - Increases maintenance burden and risk of inconsistency

    **Recommended fix:**
    Extract into a shared pytest fixture or helper function in conftest.py or tests/agent/helpers.py:

    ```python
    def make_stateful_responses(responses_factory, response_sequence):
        """Create a stateful mock response handler.

        Args:
            responses_factory: The responses factory fixture
            response_sequence: List of (function_name, server_name, params) tuples

        Returns:
            Callable suitable for use with make_mock()
        """
        state = {"i": 0}

        async def responses_create(_req):
            i = state["i"]
            state["i"] = i + 1

            if i >= len(response_sequence):
                fn_name, server_name, params = ("end_turn", "ui", {})
            else:
                fn_name, server_name, params = response_sequence[i]

            return responses_factory.make_tool_call(
                build_mcp_function(server_name, fn_name),
                params,
                call_id=f"call_{fn_name}_{i}"
            )

        return responses_create
    ```

    **Usage:**
    ```python
    # Instead of defining state + responses_create inline:
    responses = make_stateful_responses(responses_factory, [
        ("echo", "echo", {"text": "first call"}),
        ("end_turn", "ui", {}),
    ])
    s = run_server(lambda model: make_mock(responses))
    ```

    This would eliminate the duplication across all 16+ instances.
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
