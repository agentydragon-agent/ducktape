local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Path schema/docs are inconsistent with runtime behavior in internal/llm/tools; the spec (schema/docs) and implementation disagree. Resolve by aligning the declared contract with code or updating the code to meet the declared contract.
  |||,
  occurrences=[
    { files: { 'internal/llm/tools/ls.go': [{ start_line: 109, end_line: 109 }, { start_line: 119, end_line: 123 }] }, note: 'ToolInfo.Required lists "path" as required (line 109), but Run allows empty path and defaults to workingDir (lines 119-123).', expect_caught_from: [['internal/llm/tools/ls.go']] },
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 48, end_line: 104 }, { start_line: 155, end_line: 157 }] }, note: 'Description says absolute path only, but Run joins relative paths with workingDir.', expect_caught_from: [['internal/llm/tools/edit.go']] },
  ],
)
