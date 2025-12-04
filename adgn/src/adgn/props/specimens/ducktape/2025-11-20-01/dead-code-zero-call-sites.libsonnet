local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Functions with zero call sites in the codebase should be deleted as dead code.

    **Benefits:**
    - Reduces maintenance burden
    - Eliminates confusion about unused code paths
    - Improves code readability by removing noise
    - Can always restore from git history if needed
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/openai_utils/model.py': [[219, 225]],
      },
      note: 'AssistantMessageOut.from_input_item: converts AssistantMessage (input) back to AssistantMessageOut (output); reverse conversion never used',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {
        'adgn/src/adgn/openai_utils/model.py': [[280, 281], [231, 253]],
      },
      note: 'ResponsesResult.to_input_items and its only dependency response_out_item_to_input singledispatch; entire conversion-back path unused',
      expect_caught_from: [['adgn/src/adgn/openai_utils/model.py']],
    },
    {
      files: {
        'adgn/src/adgn/mcp/policy_gateway/signals.py': [[96, 145]],
      },
      note: 'detect_policy_gateway_error: 50 lines of complex error detection logic, documented as unused at line 110',
      expect_caught_from: [['adgn/src/adgn/mcp/policy_gateway/signals.py']],
    },
  ],
)
