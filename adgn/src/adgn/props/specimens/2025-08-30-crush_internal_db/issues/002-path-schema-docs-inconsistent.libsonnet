local I = import '../../specimens/lib.libsonnet';

// iss-002-path-schema-docs-inconsistent
// Path schema/docs inconsistent with behavior
//
// - `internal/llm/tools/`: inconsistent - schema/docs and behavior should be aligned:
//   - `ls.go`: ToolInfo.Required lists "path" as required, but Run allows empty path and defaults to workingDir (e.g., lines 119–123, 536–543).
//   - `edit.go`: Description (lines 48–104) says absolute path only, but Run joins relative paths with workingDir (lines 155–157).
//
// Align docs/schema and code (either make code behave as docs/schema prescribe, or update docs/schema to match behavior).

I.issueWithOccurrences(
  rationale='Path schema/docs are inconsistent with runtime behavior in internal/llm/tools; the spec (schema/docs) and implementation disagree. Resolve by aligning the declared contract with code or updating the code to meet the declared contract.',
  occurrences=[
    { files: { 'internal/llm/tools/ls.go': [{ start_line: 109, end_line: 109 }, { start_line: 119, end_line: 123 }] }, note: 'ToolInfo.Required lists "path" as required (line 109), but Run allows empty path and defaults to workingDir (lines 119-123).' },
    { files: { 'internal/llm/tools/edit.go': [{ start_line: 48, end_line: 104 }, { start_line: 155, end_line: 157 }] }, note: 'Description says absolute path only, but Run joins relative paths with workingDir.' },
  ],
  // properties=[],
)
