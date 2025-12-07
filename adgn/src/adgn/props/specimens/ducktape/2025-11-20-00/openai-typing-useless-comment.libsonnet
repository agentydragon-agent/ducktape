local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 108's comment "Removed parse_tool_call..." refers to deleted functions and should be
    removed as useless historical noise.
  |||,
  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [[108, 108]],
  },
)
