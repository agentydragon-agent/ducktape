local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Call-sites frequently chain nil checks (cfg != nil && cfg.Options != nil && cfg.Options.X != nil ...) which is noisy and error-prone. Centralize nil-safe accessors on Config (nil-receiver-safe methods) or pass *config.Config by DI to eliminate repetitive pointer chains and consolidate defaults.',
  occurrences=[
    {
      files: { 'internal/diff/external.go': [{ start_line: 41, end_line: 43 }, { start_line: 92, end_line: 93 }] },
      note: 'Example: Diff.ExternalCommand / ParseMode guarded by multi-level nil checks; centralize via config.Diff().ParseMode or a nil-safe helper.',
      expect_caught_from: [['internal/diff/external.go']],
    },
    {
      files: { 'internal/lsp/watcher/watcher.go': [{ start_line: 320, end_line: 356 }] },
      note: 'Numerous checks for cfg.Options.DebugLSP and config-derived guards; prefer config.DebugLSP()/config.CurrentLSPIgnore() helpers or DI.',
      expect_caught_from: [['internal/lsp/watcher/watcher.go']],
    },
    {
      files: { 'internal/llm/tools/tools.go': [{ start_line: 1, end_line: 30 }] },
      note: 'Representative site for reading GrepTimeoutSecs, BashBlockedCommands, MaxToolOutputBytes — prefer config.GrepTimeoutSecs(), config.BashBlockedCommands() helpers or DI.',
      expect_caught_from: [['internal/llm/tools/tools.go']],
    },
  ],
)
