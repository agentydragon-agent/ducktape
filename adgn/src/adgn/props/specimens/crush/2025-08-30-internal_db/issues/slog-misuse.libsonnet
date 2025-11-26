local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    slog.Error misuse: not passing key/value pairs when logging pragma failures (connect.go lines 34–39).

    Minimal fix example:
      slog.Error("Failed to set pragma", "pragma", pragma, "error", err)
  |||,
  filesToRanges={
    'internal/db/connect.go': [[46, 51]],  // pragma loop with slog.Error misuse
  },
)
