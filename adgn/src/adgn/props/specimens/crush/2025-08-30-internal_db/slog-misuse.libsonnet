local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    slog calls with positional arguments instead of structured key-value pairs.

    slog requires alternating string keys and values after the message: slog.Error(msg, "key1", val1, "key2", val2).

    Incorrect usage passes raw variables without key strings:
    - internal/db/connect.go:48: slog.Error("Failed to set pragma", pragma, err)
    - internal/app/lsp.go:31: slog.Error("Failed to create LSP client for", name, err)

    Should be:
    - slog.Error("Failed to set pragma", "pragma", pragma, "error", err)
    - slog.Error("Failed to create LSP client", "name", name, "error", err)

    This breaks structured logging output and makes log parsing/filtering difficult.
  |||,
  filesToRanges={
    'internal/db/connect.go': [[48, 48]],
    'internal/app/lsp.go': [[31, 31]],
  },
  expect_caught_from=[['internal/db/connect.go'], ['internal/app/lsp.go']],
)
