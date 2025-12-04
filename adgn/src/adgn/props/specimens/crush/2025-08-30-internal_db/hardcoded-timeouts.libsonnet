local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Hardcoded timeouts, intervals, and numeric limits are scattered across subsystems (LSP client, diff runner, app, watcher, agent, sourcegraph). Name these values and centralize them (either as package-level consts or configurable options) to make tuning, consistency, and discovery easier. Where appropriate, consider making them configuration options (with safe defaults). Preserve local comments about semantics when migrating to named constants.',
  occurrences=[
    {
      files: { 'internal/lsp/client.go': [{ start_line: 241, end_line: 246 }, { start_line: 312, end_line: 318 }, { start_line: 316, end_line: 319 }, { start_line: 522, end_line: 526 }] },
      note: 'LSP client: Close() uses 5*time.Second; WaitForServerReady uses 30*time.Second and ticker 500*time.Millisecond; maxFilesToOpen constant-like value 5. Define named consts like LSPStopTimeout, LSPWaitReadyTimeout, LSPReadyPollInterval, MaxFilesToOpen.',
      expect_caught_from: [['internal/lsp/client.go']],
    },
    {
      files: { 'internal/diff/external.go': [{ start_line: 54, end_line: 63 }] },
      note: 'External diff runner uses context.WithTimeout(..., 2*time.Second). Define ExternalDiffTimeout = 2 * time.Second or make configurable via config.Diff.ExternalCommand timeout.',
      expect_caught_from: [['internal/diff/external.go']],
    },
    {
      files: { 'internal/lsp/diagnostics_wait.go': [{ start_line: 24, end_line: 42 }] },
      note: 'Diagnostics wait loop uses 5s deadline and 100ms poll interval; name these constants (DiagnosticsWaitTimeout / DiagnosticsPollInterval).',
      expect_caught_from: [['internal/lsp/diagnostics_wait.go']],
    },
    {
      files: { 'internal/app/lsp.go': [{ start_line: 40, end_line: 46 }, { start_line: 118, end_line: 122 }] },
      note: 'App LSP init uses 30s init timeout; shutdown uses 5s shutdown timeout; name them LSPInitTimeout, LSPShutdownTimeout.',
      expect_caught_from: [['internal/app/lsp.go']],
    },
    {
      files: { 'internal/app/app.go': [{ start_line: 76, end_line: 81 }, { start_line: 304, end_line: 310 }, { start_line: 306, end_line: 312 }] },
      note: 'App-wide timers: middleware debounce 30ms; select/drop timeout 2s; slow-op threshold (100ms) and shutdown timeout (5s) should be named constants or config options.',
      expect_caught_from: [['internal/app/app.go']],
    },
    {
      files: { 'internal/lsp/watcher/watcher.go': [{ start_line: 64, end_line: 72 }, { start_line: 74, end_line: 80 }, { start_line: 86, end_line: 92 }] },
      note: 'Watcher defaults: debounceTime 300ms, default recursive max watched dirs 5000, default watch mode "recursive" — name these watcher defaults.',
      expect_caught_from: [['internal/lsp/watcher/watcher.go']],
    },
    {
      files: { 'internal/llm/agent/sequence_transformer.go': [{ start_line: 1, end_line: 199 }] },
      note: 'Sequence transformer timing: overall deadline 1500ms; small sleep 50ms; per-call timeout 2500ms — name and centralize as AgentSequenceTimeouts.',
      expect_caught_from: [['internal/llm/agent/sequence_transformer.go']],
    },
    {
      files: { 'internal/llm/agent/agent.go': [{ start_line: 1, end_line: 240 }] },
      note: 'Agent: 50ms delayed flush, 5s overall timeout, 200ms retry sleep — name these and consider DI/config.',
      expect_caught_from: [['internal/llm/agent/agent.go']],
    },
    {
      files: { 'internal/llm/tools/sourcegraph.go': [{ start_line: 1, end_line: 240 }] },
      note: 'Sourcegraph HTTP client timeouts: Timeout 30s, IdleConnTimeout 90s — name them and centralize.',
      expect_caught_from: [['internal/llm/tools/sourcegraph.go']],
    },
  ],
)
