local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The git_ro formatting module uses str for path fields instead of pathlib.Path. Using Path objects provides better type safety and enables path manipulation methods. Per project conventions, paths should be represented as Path objects and only converted to str at I/O boundaries.

    This affects StatusEntry (line 66), ChangedFileItem (line 88), and StatItem (line 131).
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [66]},
      note: 'StatusEntry.path is str',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [88]},
      note: 'ChangedFileItem.path is str',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [131]},
      note: 'StatItem.path is str',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
  ],
)
