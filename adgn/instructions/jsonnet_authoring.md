# Jsonnet authoring guidelines (||| blocks and issue files)

## Location and shape
- All specimen issues live under: `src/adgn_llm/properties/specimens/<specimen>/issues/*.libsonnet`
- Each file is ONE standalone Jsonnet expression that returns a single Issue object built via helpers from `specimens/lib.libsonnet`
- Start every file with: `local I = import '../../specimens/lib.libsonnet';`
- File name must equal the issue id (e.g., `issues/iss-032.libsonnet`). Do not include id in the Jsonnet; the loader derives it from the filename.

## Triple‑bar text blocks (|||) — exact house style
- Opening delimiter: exactly one space before it
  - Good: `rationale= |||`
  - Bad:  `rationale=|||` (no space) or extra spaces
- Content lines: indent every line by exactly two spaces
- Closing delimiter: two spaces + `|||,` on its own line (include the comma there)

Correct pattern:
```jsonnet
I.issueOneOccurrence(
  rationale= |||
    First line of rationale...
    Second line...
  |||,
  filesToRanges={ 'path/to/file.py': [[10, 20]] },
)
```

Common failures and fixes:
- Missing closing: add the `|||,` line (two‑space indent)
- Comma on a separate line: move the comma to the closing `|||,` line
- Ragged indent inside: normalize all content lines to two spaces
- Closing indented differently than content: use the same two‑space indent

## Choosing the right constructor (and where notes go)
- One logical occurrence spanning multiple files/ranges → use `I.issueOneOccurrence(rationale, filesToRanges=...)`
  - If you want commentary for specific ranges, put those sentences into the rationale text (bulleted or paragraph form). Do NOT put notes inside ranges for filesToRanges.
- Many independent occurrences (each can have its own note) → use `I.issueWithOccurrences(rationale, occurrences=[{ files: {...}, note: '...' }, ...])` or `I.issueOccurrencesFromLines(rationale, linesByFile={ ... })`
  - `issueWithOccurrences` supports per‑occurrence `note` strings.
  - `issueOccurrencesFromLines` supports shorthand entries (numbers, [start,end], or strings to serve as occurrence‑level notes on unspecified ranges).

## Valid range specs by helper
- filesToRanges (for `issueOneOccurrence`):
  - Allowed per‑file entries: `null` (unspecified), `[]` (unspecified), `[line]` (single), `[start,end]` (span), or objects `{ start_line: n, end_line?: m }`
  - NOT allowed: tuples with strings (e.g., `[137, 143, 'note']` or `[133, 'why']`) — move such note text into the rationale (bullet per file/lines)
- linesByFile (for `issueOccurrencesFromLines`):
  - Allowed per‑file entries: numbers, `[start,end]`, strings (become occurrence‑level note with unspecified range), or `{range: <spec>, note: '...'}`

## Import/search path
- Always import helpers via a relative path from the `issues/` directory: `local I = import '../../specimens/lib.libsonnet';`
- The loader sets the library path; do not chdir or edit imports in‑place.

## Trailing commas & monolith split
- Each issue file is a standalone expression; remove aggregator‑style trailing commas at the end of the expression.
- Keep commas only between arguments and after the closing `|||` line.

## Quick examples of wrong vs right (|||)
Wrong (comma alone after closing):
```jsonnet
rationale= |||
  Text
|||
  ,
```
Right:
```jsonnet
rationale= |||
  Text
|||,
```
Wrong (no closing):
```jsonnet
rationale= |||
  Text
,
```
Right (balanced):
```jsonnet
rationale= |||
  Text
|||,
```
