local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The git_ro formatting module uses single-character strings for status fields instead of the appropriate pygit2 enums. Pygit2 provides GIT_DELTA_* constants (e.g., GIT_DELTA_ADDED, GIT_DELTA_MODIFIED, GIT_DELTA_DELETED, GIT_DELTA_RENAMED) for delta status and GIT_STATUS_* constants for working tree and index status.

    Using string literals like "M", "A", "D", "R" loses type safety and requires manual mapping. Pydantic can serialize enums appropriately, so the models should use the native pygit2 enum types instead of str fields.

    This applies to StatusEntry (lines 68-69 for index and worktree fields) and ChangedFileItem (line 89 for status field).
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [[68, 69]]},
      note: 'StatusEntry uses str for index and worktree instead of GIT_STATUS_* enums',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/git_ro/formatting.py': [89]},
      note: 'ChangedFileItem uses str for status instead of GIT_DELTA_* enum',
      expect_caught_from: [['adgn/src/adgn/mcp/git_ro/formatting.py']],
    },
  ],
)
