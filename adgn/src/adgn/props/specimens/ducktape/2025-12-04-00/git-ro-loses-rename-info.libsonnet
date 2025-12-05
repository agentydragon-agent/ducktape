local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The git_ro formatting module loses path information when handling renamed files. For renamed files, both old_file.path and new_file.path are available from pygit2, but the code collapses this to a single path field, losing the rename information.

    This affects both ChangedFileItem (lines 113-116) and StatItem (lines 158-161). The pattern `(d.new_file.path or d.old_file.path) if d.new_file else d.old_file.path` selects one path but discards the other, making it impossible for callers to determine the source and destination of a rename operation.

    The proper solution is to preserve both paths in the model and let callers interpret them based on the status field.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [[113, 116]]},
      note: 'ChangedFileItem construction loses rename path information',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [[158, 161]]},
      note: 'StatItem construction loses rename path information',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
  ],
)
