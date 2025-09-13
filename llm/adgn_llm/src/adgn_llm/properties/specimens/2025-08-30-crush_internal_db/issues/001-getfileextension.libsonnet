local I = import '../../specimens/lib.libsonnet';

// iss-001-getfileextension
// Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths),
// not an extension; rename and update doc to reflect actual return value.

I.issueOneOccurrence(
  rationale='Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths), not an extension; rename and update doc to reflect actual return value.',
  // properties=['truthfulness'],
  filesToRanges={
    'internal/tui/components/chat/messages/renderer.go': [[424, 434]],
  },
)
