local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 320 wraps a Path in str() when passing to pygit2.Repository().
    pygit2 accepts pathlib.Path directly since version 1.0, making the str()
    conversion redundant. Same pattern appears in tests and other source files.

    Fix: Remove str() wrapper - pygit2.Repository(repo_path) instead of
    pygit2.Repository(str(repo_path)).
  |||,
  filesToRanges={'wt/src/wt/client/wt_client.py': [[320, 320]]},
)
