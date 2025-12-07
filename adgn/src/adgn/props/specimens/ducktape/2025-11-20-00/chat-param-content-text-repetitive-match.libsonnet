local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    chat_param_message_content_as_text (lines 75-105) has repetitive match cases with nearly
    identical logic for each role. Instead of handling each role separately (ASSISTANT, USER,
    SYSTEM, TOOL/FUNCTION/DEVELOPER) with duplicated content-parsing code, it could have a single
    upfront check that the role is in a list of understood roles (fail-fast if not), then apply
    the same content-parsing logic for all cases.
  |||,
  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [[80, 105]],
  },
)
