local I = import '../../specimens/lib.libsonnet';

// iss-040: Useless comment "# Logging and config"

I.issueOneOccurrence(
  rationale=|||
    Line 722 comment says "# Logging and config" immediately before calling
    `_init_logging()` and `AppConfig.resolve()`. This just restates what the
    code obviously does.

    **Fix:** Delete the comment.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      722,  // Useless comment restating code
    ],
  },
)
