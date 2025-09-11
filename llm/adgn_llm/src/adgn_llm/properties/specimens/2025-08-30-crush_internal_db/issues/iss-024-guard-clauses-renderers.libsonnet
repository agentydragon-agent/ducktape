local I = import '../../specimen_issues.libsonnet';

// iss-024-guard-clauses-renderers
// Prefer guard-clause (early bailout) style when unmarshalling params in renderer Render methods

I.issueWithOccurrences(
  id='iss-024-guard-clauses-renderers',
  rationale='Many renderer.Render implementations decode JSON params with `if err := json.Unmarshal(...); err == nil { ... }` and then build args inside the success branch. Prefer failing-fast guard clauses (if err := json.Unmarshal(...); err != nil { return fallback } ) and proceed on the happy path to reduce nesting and improve readability. The Bash renderer already uses the guard-clause style.',
  properties=['early-bailout'],
  occurrences=[
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 290, end_line: 297 } ] }, note: 'editRenderer.Render: use guard clause for json unmarshal of params, proceed on happy path.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 335, end_line: 344 } ] }, note: 'multiEditRenderer.Render: use guard clause for params unmarshal.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 384, end_line: 390 } ] }, note: 'writeRenderer.Render: prefer guard-clause style when unmarshalling params.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 410, end_line: 416 } ] }, note: 'fetchRenderer.Render: use early bailout on unmarshal error then happy-path.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 457, end_line: 463 } ] }, note: 'downloadRenderer.Render: prefer guard-clause for metadata/params parsing.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 483, end_line: 488 } ] }, note: 'globRenderer.Render: use guard-clause pattern.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 508, end_line: 515 } ] }, note: 'grepRenderer.Render: prefer early-return on unmarshal error then continue.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 535, end_line: 543 } ] }, note: 'lsRenderer.Render: use guard clause for unmarshalling params.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 563, end_line: 569 } ] }, note: 'sourcegraphRenderer.Render: prefer guard-clause for params/metadata parsing.' },
  ],
)
