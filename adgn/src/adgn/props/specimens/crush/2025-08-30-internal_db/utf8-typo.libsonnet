local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Identifier typo: `isValidUt8` appears to be a misspelling of `isValidUTF8` (typo of UTF8). Correct identifier improves clarity/truthfulness of code and avoids confusion.
  |||,
  occurrences=[
    { files: { 'internal/llm/tools/fetch.go': [{ start_line: 188, end_line: 191 }] }, note: 'isValidUt8 := utf8.ValidString(content) — rename to isValidUTF8', expect_caught_from: [['internal/llm/tools/fetch.go']] },
    { files: { 'internal/llm/tools/view.go': [{ start_line: 226, end_line: 230 }] }, note: 'isValidUt8 := utf8.ValidString(content) — rename to isValidUTF8', expect_caught_from: [['internal/llm/tools/view.go']] },
  ],
)
