local I = import '../../lib.libsonnet';


I.issue(
  rationale='The same history bookkeeping sequence (ensure file exists, create initial if missing, createVersion when content differs, then always createVersion for new content) is duplicated across edit/delete/replace/write flows. Extract a small helper in the history package (or tools package) to centralize this logic and make intent explicit: EnsureFileVersion(ctx, files, sessionID, filePath, oldContent, newContent).',
  filesToRanges={
    'internal/llm/tools/edit.go': [[379, 400], [518, 538]],
    'internal/llm/tools/write.go': [[204, 224]],
  },
  expect_caught_from=[['internal/llm/tools/edit.go'], ['internal/llm/tools/write.go']],
)
