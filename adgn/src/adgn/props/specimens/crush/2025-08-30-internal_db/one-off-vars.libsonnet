local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Inline single-use temporaries and trivial wrapper locals (prefer struct literals or direct expressions) to reduce noise and make intent clearer.
  |||,
  occurrences=[
    { files: { 'internal/csync/maps.go': [{ start_line: 111, end_line: 114 }] }, note: 'JSONSchemaAlias returns a throwaway temp map `m` — inline the literal return value.', expect_caught_from: [['internal/csync/maps.go']] },
    { files: { 'internal/format/spinner.go': [{ start_line: 44, end_line: 69 }] }, note: 'NewSpinner builds a local `model` and `prog` only used once to construct Spinner — inline into the returned struct where sensible.', expect_caught_from: [['internal/format/spinner.go']] },
    { files: { 'internal/session/session.go': [{ start_line: 150, end_line: 156 }] }, note: 'NewService creates a one-off `broker` local and then returns a struct containing it — inline into the struct literal.', expect_caught_from: [['internal/session/session.go']] },
    { files: { 'internal/config/provider.go': [{ start_line: 82, end_line: 85 }] }, note: 'Providers(): inline one-off locals `client := catwalk.NewWithURL(...)` and `path := providerCacheFileData()` into the call site or helper to reduce noise.', expect_caught_from: [['internal/config/provider.go']] },
    { files: { 'internal/lsp/watcher/watcher.go': [{ start_line: 568, end_line: 576 }] }, note: 'isPathWatched: `isMatch` is assigned then returned immediately; return expression directly or inline the match check.', expect_caught_from: [['internal/lsp/watcher/watcher.go']] },
    { files: { 'internal/lsp/watcher/watcher.go': [{ start_line: 653, end_line: 672 }] }, note: 'matchesSimpleGlob: several single-use `isMatch` temporaries in the ** handling branch can be inlined into their return expressions.', expect_caught_from: [['internal/lsp/watcher/watcher.go']] },
  ],
)
