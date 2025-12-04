local I = import '../../lib.libsonnet';

// iss-001-getfileextension
// Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths),
// not an extension; rename and update doc to reflect actual return value.

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='Misleading name/doc: `getFileExtension` returns synthesized file names (fake paths), not an extension; rename and update doc to reflect actual return value.',
  filesToRanges={
    'internal/tui/components/chat/messages/renderer.go': [[424, 434]],
  },
)
