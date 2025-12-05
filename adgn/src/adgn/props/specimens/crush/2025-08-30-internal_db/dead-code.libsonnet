local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='Remove unreachable or redundant code paths (dead code). Delete unreachable branches and simplify conditionals that return identical results to avoid confusion and maintenance burden.',
  occurrences=[
    {
      files: { 'internal/lsp/watcher/watcher.go': [{ start_line: 699, end_line: 709 }] },
      note: 'Second `if basePath == ""` branch is unreachable because earlier branch already handled basePath==""; remove the dead branch.',
      expect_caught_from: [['internal/lsp/watcher/watcher.go']],
    },
    {
      files: { 'internal/tui/components/chat/messages/tool.go': [{ start_line: 200, end_line: 213 }] },
      note: 'View(): both nested and non-nested branches return the same `box.Render(content)`; remove the conditional and return once.',
      expect_caught_from: [['internal/tui/components/chat/messages/tool.go']],
    },
  ],
)
