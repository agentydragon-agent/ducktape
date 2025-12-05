local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Many tools duplicate the pattern `WithResponseMetadata(NewTextResponse(text), SomeResponseMetadata{...})`. Introduce a small helper (e.g., WrapTextWithMeta(text string, meta any) (ToolResponse, error)) and per-tool unexported constructors to reduce duplication and clarify metadata shaping.
  |||,
  occurrences=[
    { files: { 'internal/llm/tools/glob.go': [{ start_line: 133, end_line: 134 }] }, note: 'Glob tool uses WithResponseMetadata/NewTextResponse at these lines; factor via WrapTextWithMeta.', expect_caught_from: [['internal/llm/tools/glob.go']] },
    { files: { 'internal/llm/tools/bash.go': [{ start_line: 487, end_line: 490 }] }, note: 'Bash tool wraps stdout/no-output with BashResponseMetadata - use helper to centralize.', expect_caught_from: [['internal/llm/tools/bash.go']] },
    { files: { 'internal/llm/tools/view.go': [{ start_line: 249, end_line: 251 }] }, note: 'View tool wraps output and ViewResponseMetadata at these lines; extract per-tool helper delegating to WrapTextWithMeta.', expect_caught_from: [['internal/llm/tools/view.go']] },
    { files: { 'internal/llm/tools/write.go': [{ start_line: 236, end_line: 237 }] }, note: 'Write tool wraps result with WriteResponseMetadata - consolidate.', expect_caught_from: [['internal/llm/tools/write.go']] },
    { files: { 'internal/llm/tools/grep.go': [{ start_line: 175, end_line: 177 }] }, note: 'Grep wraps matches with GrepResponseMetadata; prefer a per-tool helper.', expect_caught_from: [['internal/llm/tools/grep.go']] },
    { files: { 'internal/llm/tools/ls.go': [{ start_line: 181, end_line: 183 }] }, note: 'LS wraps listing output with LSResponseMetadata; centralize call shape.', expect_caught_from: [['internal/llm/tools/ls.go']] },
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 267, end_line: 269 }, { start_line: 404, end_line: 406 }, { start_line: 543, end_line: 545 }] }, note: 'Edit tool has multiple wrap sites; provide newEditResult helper that uses WrapTextWithMeta.', expect_caught_from: [['internal/llm/tools/edit.go']] },
    { files: { 'internal/llm/tools/multiedit.go': [{ start_line: 313, end_line: 315 }, { start_line: 454, end_line: 456 }] }, note: 'MultiEdit uses MultiEditResponseMetadata in multiple places; factor to helper.', expect_caught_from: [['internal/llm/tools/multiedit.go']] },
  ],
)
