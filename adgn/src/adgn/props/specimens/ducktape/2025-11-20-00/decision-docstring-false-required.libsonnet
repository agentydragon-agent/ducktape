local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The Decision class docstring claims "All fields are REQUIRED", but the reason field is
    str | None = None (optional). The docstring should be simplified to just the first line:
    "Decision made about a tool call." The statement about required fields is misleading and
    the note about Decision being optional on ToolCallRecord is redundant with the type
    annotation on ToolCallRecord itself.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/__init__.py': [[91, 95]],
  },
)
