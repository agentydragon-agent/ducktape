local I = import '../../specimens/lib.libsonnet';

// iss-041: Misleading comment - include_all is from argparse, not passthru

I.issueOneOccurrence(
  rationale=|||
    Line 717 comment says "Parse flags from passthru (those not handled by argparse)"
    but line 719 sets `include_all = args.stage_all`, which IS from argparse (parsed
    by `-a/--all` flag at line 485).

    The comment/positioning is misleading. Only `is_amend` is actually parsed from
    passthru.

    **Current:**
    ```python
    # Parse flags from passthru (those not handled by argparse)
    is_amend = "--amend" in passthru
    include_all = args.stage_all
    ```

    **Fix:** Move `include_all` line before the comment, or delete the comment
    entirely since it's obvious what the code does.

    **Better:** Delete `include_all` variable entirely (see issue 042).
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [717, 719],  // Comment incorrectly implies include_all is from passthru
    ],
  },
)
