local I = import '../../lib.libsonnet';

// iss-010-remove-deadcode-comment
// Not-useful historical comment: remove "deadcode pruned: emitStage1 was unused" from e2e/mock_openai_responses.go

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='Historical "deadcode pruned" comment appears to document an edit history ("emitStage1 was unused") and is no longer useful to readers; delete the comment to avoid confusion.',
  filesToRanges={
    'e2e/mock_openai_responses.go': [[218, 219]],
  },
)
