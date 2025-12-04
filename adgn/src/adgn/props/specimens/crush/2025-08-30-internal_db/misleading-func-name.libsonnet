local I = import '../../lib.libsonnet';


I.issue(
  rationale='Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths), not an extension; rename and update doc to reflect actual return value.',
  filesToRanges={
    'internal/tui/components/chat/messages/renderer.go': [[424, 434]],
  },
)
