local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `.messages` property (lines 626-656) is a thin wrapper around `_to_openai_input_items()` (lines 431-448).
    These should be merged into a single public method named `.to_openai_messages()` for clarity. Using a
    method name instead of a property better signals that this performs a non-trivial conversion (creating
    a new list with transformed items) rather than just accessing state. The "to_" prefix explicitly indicates
    this converts to an external format (OpenAI's), not our internal format.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/agent.py': [
      [626, 656],  // .messages property
      [431, 448],  // _to_openai_input_items implementation
    ],
  },
)
