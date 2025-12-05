local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Filesystem paths constructed via string concatenation instead of filepath.Join.

    String concatenation with "/" hardcodes Unix path separators and fails on Windows (backslash separators). filepath.Join handles OS-specific separators and cleans redundant slashes.

    Impact: Code fails on Windows; non-portable and non-idiomatic.
  |||,
  occurrences=[
    {
      files: { 'internal/diff/word_inline.go': [[43, 44]] },
      note: 'dir + "/old", dir + "/new" → filepath.Join(dir, "old"), filepath.Join(dir, "new")',
      expect_caught_from: [['internal/diff/word_inline.go']],
    },
    {
      files: { 'internal/cmd/root.go': [[147, 147], [151, 151], [152, 152]] },
      note: 'dataDir + "/logs/..." → filepath.Join(dataDir, "logs", ...)',
      expect_caught_from: [['internal/cmd/root.go']],
    },
    {
      files: { 'e2e/scenario_live_basic_test.go': [[44, 44]] },
      note: 'sc.ArtifactDir + "/logs/provider-wire.log" → filepath.Join(sc.ArtifactDir, "logs", "provider-wire.log")',
      expect_caught_from: [['e2e/scenario_live_basic_test.go']],
    },
    {
      files: { 'internal/config/provider_empty_test.go': [[20, 20], [33, 33]] },
      note: 't.TempDir() + "/providers.json" → filepath.Join(t.TempDir(), "providers.json")',
      expect_caught_from: [['internal/config/provider_empty_test.go']],
    },
    {
      files: { 'internal/config/provider_test.go': [[30, 30], [44, 44], [69, 69]] },
      note: 't.TempDir() + "/providers.json" → filepath.Join(t.TempDir(), "providers.json")',
      expect_caught_from: [['internal/config/provider_test.go']],
    },
  ],
)
