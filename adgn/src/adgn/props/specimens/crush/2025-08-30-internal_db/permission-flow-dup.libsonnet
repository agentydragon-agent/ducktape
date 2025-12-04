local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    A ~30-line sequence (generate diff, build permission.CreatePermissionRequest, write file, history bookkeeping, recordFileWrite/read) is duplicated across multiple branches in internal/llm/tools/edit.go. Extract a single helper parameterized by action, description, and params to centralize permission, diff, write, history bookkeeping and avoid drift.
  |||,
  occurrences=[
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 226, end_line: 275 }] }, note: 'createNewFile branch: diff+permission+write+history+record bookkeeping.', expect_caught_from: [['internal/llm/tools/edit.go']] },
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 349, end_line: 406 }] }, note: 'deleteContent branch: diff+permission+write+history+record bookkeeping (similar pattern).', expect_caught_from: [['internal/llm/tools/edit.go']] },
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 488, end_line: 550 }] }, note: 'replaceContent branch: same sequence; extract helper EnsureWriteWithHistory(ctx, files, sessionID, filePath, oldContent, newContent, action, desc, params...).', expect_caught_from: [['internal/llm/tools/edit.go']] },
  ],
)
