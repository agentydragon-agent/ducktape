local I = import '../../specimen_issues.libsonnet';

// iss-022-history-lsp-bookkeeping
// History/LSP bookkeeping: extract helper to DRY repeated "get/create/createVersion" sequences.

I.issueOneOccurrence(
  rationale='The same history bookkeeping sequence (ensure file exists, create initial if missing, createVersion when content differs, then always createVersion for new content) is duplicated across edit/delete/replace/write flows. Extract a small helper in the history package (or tools package) to centralize this logic and make intent explicit: EnsureFileVersion(ctx, files, sessionID, filePath, oldContent, newContent).',
  properties=[],
  filesToRanges={
    'internal/llm/tools/edit.go': [[379, 400], [518, 538]],
    'internal/llm/tools/write.go': [[204, 224]],
  },
)
