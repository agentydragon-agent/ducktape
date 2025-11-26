local I = import '../../specimens/lib.libsonnet';

// iss-031: Useless comments that restate obvious code

I.issueWithOccurrences(
  rationale= |||
    Multiple locations have comments that merely restate what the code obviously does,
    or document historical changes rather than current behavior. These comments add
    no value and should be deleted.

    **General principle:**
    Comments should explain WHY or provide non-obvious context. Comments that just
    describe WHAT the code does (when it's already clear) are noise.
  |||,
  occurrences=[
    {
      // Comment says "Capture -a/--all (staging flag) to remove from passthru"
      // This is obvious - argparse automatically removes handled flags from unknown args
      // The comment documents a delta from a previous version, not current behavior
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [484],
      },
    },
    {
      // Comment "# Logging and config" before calling _init_logging() and AppConfig.resolve()
      // Just restates what the code obviously does
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [722],
      },
    },
    {
      // Comment "Parse flags from passthru (those not handled by argparse)" is misleading
      // Line 719 sets include_all = args.stage_all which IS from argparse
      // Only is_amend is actually parsed from passthru
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [[717, 719]],
      },
    },
  ],
)
