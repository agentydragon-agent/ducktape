local I = import '../../specimens/lib.libsonnet';

// iss-031-spinning-simplify
// Simplify ToolCallCmp.Spinning(): early-return when nested is spinning, then return m.spinning

I.issueOneOccurrence(
  rationale='ToolCallCmp.Spinning currently checks m.spinning, then iterates nested.Spinning and returns true, and finally returns m.spinning. Simplify to early-return on nested.Spining() and then return m.spinning at the end to make the intent clearer.',
  // properties=['minimize-nesting'],
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[994, 1004]],
  },
)
