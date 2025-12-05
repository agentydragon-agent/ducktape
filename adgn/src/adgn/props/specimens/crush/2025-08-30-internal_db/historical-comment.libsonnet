local I = import '../../lib.libsonnet';


I.issue(
  rationale='Historical "deadcode pruned" comment appears to document an edit history ("emitStage1 was unused") and is no longer useful to readers; delete the comment to avoid confusion.',
  filesToRanges={
    'e2e/mock_openai_responses.go': [[218, 219]],
  },
)
