local I = import '../../specimen_issues.libsonnet';

// iss-012-collapse-blanklines
// Collapse double blank lines in struct Options: keep at most one blank line between logical groups.

I.issueOneOccurrence(
  rationale='Collapse double blank lines in internal/config/config.go Options struct; keep at most one blank line between logical groups or use a header comment (e.g., "// ---- Tool options ----") with exactly one blank line above it.',
  properties=['no-useless-docs'],
  filesToRanges={
    'internal/config/config.go': [[166, 176]],
  },
)
