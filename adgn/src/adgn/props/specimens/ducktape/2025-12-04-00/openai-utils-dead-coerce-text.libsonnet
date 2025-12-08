local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `_coerce_text` validator (lines 218-230) in `AssistantMessageOut` is dead code. It attempts to coerce string or dict inputs with a "text" field into the proper `{"parts": [...]}` format, but this coercion is never used.

    All construction sites in the file construct AssistantMessageOut directly with the correct type:
    - Line 294 (`_message_output_to_assistant`): `AssistantMessageOut(parts=parts)` where `parts` is `list[OutputText]`
    - Line 251 (`from_input_item` method): `cls(parts=parts)` where `parts` is `list[OutputText]`

    Neither construction site passes a string or a dict with "text" field that would trigger the validator's coercion logic. The validator adds complexity without providing any value.

    Delete the `_coerce_text` validator entirely.
  |||,
  filesToRanges={'adgn/src/adgn/openai_utils/model.py': [[218, 230]]},
)
