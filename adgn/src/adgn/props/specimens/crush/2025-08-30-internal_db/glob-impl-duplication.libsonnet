local I = import '../lib.libsonnet';

// iss-018-glob-dedup
// Deduplicate glob matching: standardize on doublestar.Match or isolate matching behind a helper.

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='Codebase contains two different glob implementations: watcher.go implements custom matchesGlob/matchesSimpleGlob while internal/fsext/fileutil.go uses doublestar.Match. Standardize on a single, well-documented implementation (prefer doublestar if it covers required semantics) or wrap matching behind a small helper API so semantics are explicit and maintained in one place.',
  filesToRanges={
    'internal/lsp/watcher/watcher.go': [[583, 672]],
    'internal/fsext/fileutil.go': [[1, 196]],
  },
)
