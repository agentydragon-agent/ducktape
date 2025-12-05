local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 161-164 discover and create a pygit2 repository inside
    `generate_commit_message_minicodex()`, violating dependency injection.
    The function creates its own dependencies instead of receiving them.

    Problems: harder to test (can't inject test repository), duplicates
    discovery logic (caller at cli.py:704 already has repo), tight coupling
    to current working directory.

    Fix: accept `repo: pygit2.Repository` parameter and pass it through from
    the caller. The MCP server created internally should also use the injected
    repository instead of discovering its own.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      [158, 164],  // Function creates repo instead of receiving it
    ],
  },
)
