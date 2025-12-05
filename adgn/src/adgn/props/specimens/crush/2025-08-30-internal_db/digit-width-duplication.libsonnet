local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Duplicate digit-width logic exists: view.addLineNumbers uses a fixed 6-character width; renderer.renderCodeContent computes digits via getDigits. Extract a shared Digits helper in internal/format/lineno while keeping rendering differences (LLM vs human) separate.',
  occurrences=[
    {
      files: { 'internal/llm/tools/view.go': [{ start_line: 258, end_line: 276 }] },
      note: 'addLineNumbers uses fixed 6-char padding via fmt.Sprintf("%6s", numStr). Consider Digits helper and minimal adaptation.',
      expect_caught_from: [['internal/llm/tools/view.go']],
    },
    {
      files: { 'internal/tui/components/chat/messages/renderer.go': [{ start_line: 817, end_line: 883 }] },
      note: 'renderCodeContent uses getDigits dynamic digit counting; keep rendering behavior separate for UI but extract shared Digits helper.',
      expect_caught_from: [['internal/tui/components/chat/messages/renderer.go']],
    },
  ],
)
