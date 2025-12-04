local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Filesystem paths constructed via string concatenation instead of filepath.Join.

    String concatenation with "/" hardcodes Unix path separators and fails on Windows (backslash separators). filepath.Join handles OS-specific separators and cleans redundant slashes.

    Occurrences:
    - internal/diff/word_inline.go:43-44: dir + "/old", dir + "/new"
    - internal/cmd/root.go:147,151,152: dataDir + "/logs/..."
    - e2e/scenario_live_basic_test.go:44: sc.ArtifactDir + "/logs/provider-wire.log"
    - internal/config/provider_empty_test.go:20,33: t.TempDir() + "/providers.json"
    - internal/config/provider_test.go:30,44,69: t.TempDir() + "/providers.json"

    Examples:
    - dir + "/old" → filepath.Join(dir, "old")
    - dataDir + "/logs/crush.log" → filepath.Join(dataDir, "logs", "crush.log")
    - t.TempDir() + "/providers.json" → filepath.Join(t.TempDir(), "providers.json")

    Impact: Code fails on Windows; non-portable and non-idiomatic.
  |||,
  filesToRanges={
    'internal/diff/word_inline.go': [[43, 44]],
    'internal/cmd/root.go': [[147, 147], [151, 151], [152, 152]],
    'e2e/scenario_live_basic_test.go': [[44, 44]],
    'internal/config/provider_empty_test.go': [[20, 20], [33, 33]],
    'internal/config/provider_test.go': [[30, 30], [44, 44], [69, 69]],
  },
  expect_caught_from=[['internal/diff/word_inline.go'], ['internal/cmd/root.go'], ['e2e/scenario_live_basic_test.go'], ['internal/config/provider_empty_test.go'], ['internal/config/provider_test.go']],
)
