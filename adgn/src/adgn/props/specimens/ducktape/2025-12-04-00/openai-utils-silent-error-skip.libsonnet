local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `_message_output_to_assistant` function (lines 281-294) returns `AssistantMessageOut | None`, and when it returns None (lines 292-293), the caller (lines 330-332) silently skips adding the item to `out_items`.

    This is dangerous for two reasons:

    1. **OpenAI reasoning sensitivity**: OpenAI's reasoning feature is sensitive to being placed in exactly the same prefix it was sampled from. Silently dropping messages breaks this invariant and can cause subtle bugs.

    2. **Silent error hiding**: If `_message_output_to_assistant` returns None because something went wrong (no parts found), this should be treated as an error that surfaces immediately, not silently ignored.

    The function should be changed to either:
    - Return a non-nullable `AssistantMessageOut` and raise an exception when parts is empty, OR
    - Have the caller raise an exception when None is returned instead of silently skipping

    Errors must cause breakage/raise, not be silently skipped.
  |||,
  filesToRanges={
    'adgn/src/adgn/openai_utils/model.py': [
      [281, 281],  // Nullable return type
      [292, 293],  // Returns None when no parts
      [330, 332],  // Silently skips None result
    ],
  },
)
