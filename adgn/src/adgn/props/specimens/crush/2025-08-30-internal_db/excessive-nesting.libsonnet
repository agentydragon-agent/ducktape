local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Prefer early returns/continues to reduce nesting and make happy-path obvious. Replace large wrapped bodies guarded by a single conditional with small guard-clauses (return/continue) at the top where appropriate.',
  occurrences=[
    {
      files: { 'internal/logging/recover.go': [{ start_line: 11, end_line: 24 }] },
      note: 'RecoverPanic currently wraps its whole body in a recover-check; prefer early-return guard or narrower scope to reduce nesting.',
      expect_caught_from: [['internal/logging/recover.go']],
    },
    {
      files: { 'internal/app/lsp_events.go': [{ start_line: 63, end_line: 85 }] },
      note: 'updateLSPState/updateLSPDiagnostics wrap large blocks; prefer early return/guard clauses where applicable.',
      expect_caught_from: [['internal/app/lsp_events.go']],
    },
    {
      files: { 'internal/lsp/client.go': [{ start_line: 425, end_line: 435 }] },
      note: 'openKeyConfigFiles: when a file does not exist, use continue to skip rather than nesting the rest of the body.',
      expect_caught_from: [['internal/lsp/client.go']],
    },
    {
      files: { 'internal/app/app.go': [{ start_line: 426, end_line: 429 }] },
      note: 'cleanup loop: use continue when cleanup is nil to avoid wrapping body in an extra nesting level.',
      expect_caught_from: [['internal/app/app.go']],
    },
    {
      files: { 'internal/shell/shell.go': [{ start_line: 183, end_line: 201 }] },
      note: 'ArgumentsBlocker: guard with continue when args length is insufficient rather than nesting the matching body.',
      expect_caught_from: [['internal/shell/shell.go']],
    },
  ],
)
