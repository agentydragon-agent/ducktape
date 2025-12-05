local I = import '../../lib.libsonnet';


I.issue(
  rationale='ToolCallCmp.Spinning currently checks m.spinning, then iterates nested.Spinning and returns true, and finally returns m.spinning. Simplify to early-return on nested.Spining() and then return m.spinning at the end to make the intent clearer.',
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[994, 1004]],
  },
)
