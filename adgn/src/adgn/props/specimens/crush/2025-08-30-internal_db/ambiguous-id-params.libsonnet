local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Function parameters named generically `id` are ambiguous; prefer explicit names like `messageID` or `sessionID` to make intent/units obvious and avoid accidental misuses.',
  occurrences=[
    {
      files: { 'internal/message/middleware/debounce.go': [{ start_line: 33, end_line: 41 }, { start_line: 94, end_line: 105 }] },
      note: 'debounce.getOrCreate/deleteEntry/Delete use `id string` where this represents message IDs — rename to messageID.',
      expect_caught_from: [['internal/message/middleware/debounce.go']],
    },
    {
      files: { 'internal/message/middleware/serialized.go': [{ start_line: 27, end_line: 36 }, { start_line: 134, end_line: 141 }, { start_line: 134, end_line: 152 }] },
      note: 'sessionWorker.id / newSessionWorker(id) / Delete(ctx,id) opaque `id` represents sessionID or messageID in different contexts — make names explicit.',
      expect_caught_from: [['internal/message/middleware/serialized.go']],
    },
    {
      files: { 'internal/message/message.go': [{ start_line: 61, end_line: 72 }, { start_line: 239, end_line: 246 }] },
      note: 'Service.Delete(ctx, id string) and other interfaces use `id` param name — prefer messageID for clarity across API boundaries.',
      expect_caught_from: [['internal/message/message.go']],
    },
  ],
)
