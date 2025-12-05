local I = import '../../lib.libsonnet';


I.issue(
  rationale='Collapse double blank lines in internal/config/config.go Options struct; keep at most one blank line between logical groups or use a header comment (e.g., "// ---- Tool options ----") with exactly one blank line above it.',
  filesToRanges={
    'internal/config/config.go': [[166, 176]],
  },
)
