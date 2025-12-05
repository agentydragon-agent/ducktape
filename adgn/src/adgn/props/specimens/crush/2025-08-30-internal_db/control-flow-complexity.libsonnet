local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Code can be simplified to shorten or reduce nesting without hurting readability. Prefer combining trivial nested conditionals, using early returns/continues, or small guard-clauses to make the happy path obvious (see Early bailout).',
  occurrences=[
    {
      files: { 'internal/tui/components/chat/chat.go': [{ start_line: 508, end_line: 516 }, { start_line: 837, end_line: 841 }] },
      note: 'Combine nested type+value checks into single if (e.g., asMsg,ok := item.(MessageCmp); ok && asMsg.GetMessage().ID == messageID) and guard for tc.Spinning with a single condition.',
      expect_caught_from: [['internal/tui/components/chat/chat.go']],
    },
    {
      files: { 'internal/message/content.go': [{ start_line: 211, end_line: 300 }] },
      note: 'Flatten nested type/id/finished guards across Content/Reasoning/Finish helper methods to reduce repetition and nesting.',
      expect_caught_from: [['internal/message/content.go']],
    },
    {
      files: { 'internal/app/app.go': [{ start_line: 310, end_line: 319 }] },
      note: 'Flatten trivial guards when deriving MCP topic; prefer small guard or local helper to reduce nesting in the hot loop.',
      expect_caught_from: [['internal/app/app.go']],
    },
    {
      files: { 'internal/lsp/client.go': [{ start_line: 340, end_line: 356 }] },
      note: 'WaitForServerReady: remove unnecessary else after an early return and use guard clauses.',
      expect_caught_from: [['internal/lsp/client.go']],
    },
    {
      files: { 'e2e/scenario.go': [{ start_line: 196, end_line: 201 }] },
      note: 'Combine E2E_PER_STEP_SECS env read and value check into a single expression (read+parse+validate) to reduce nested conditionals.',
      expect_caught_from: [['e2e/scenario.go']],
    },
    {
      files: { 'internal/pubsub/broker.go': [{ start_line: 180, end_line: 184 }] },
      note: 'Use short if with initializer: if s := f.String(); s != "" { ... } instead of separate lines.',
      expect_caught_from: [['internal/pubsub/broker.go']],
    },
    {
      files: { 'internal/history/file.go': [{ start_line: 77, end_line: 115 }] },
      note: 'createWithVersion: flatten UNIQUE-constraint retry guard; use clearer retry loop and guard-clauses to avoid deep nesting.',
      expect_caught_from: [['internal/history/file.go']],
    },
  ],
)
