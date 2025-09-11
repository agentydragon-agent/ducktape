local I = import '../../specimen_issues.libsonnet';

// iss-030-digit-counting
// Digit counting for line numbers: extract a shared Digits(n int) helper but preserve separate rendering behaviour for LLM vs human surfaces.

I.issueWithOccurrences(
  id='iss-030-digit-counting',
  rationale='Duplicate digit-width logic exists: view.addLineNumbers uses a fixed 6-character width; renderer.renderCodeContent computes digits via getDigits. Extract a shared Digits helper in internal/format/lineno while keeping rendering differences (LLM vs human) separate.',
  properties=[],
  occurrences=[
    { files: { 'internal/llm/tools/view.go': [ { start_line: 258, end_line: 276 } ] }, note: 'addLineNumbers uses fixed 6-char padding via fmt.Sprintf("%6s", numStr). Consider Digits helper and minimal adaptation.' },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [ { start_line: 817, end_line: 883 } ] }, note: 'renderCodeContent uses getDigits dynamic digit counting; keep rendering behavior separate for UI but extract shared Digits helper.' },
  ],
)
