local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 522-529 define `filter_commit_passthru()` which just returns its input
    unchanged. The function's own comment admits it "may be removed in future."

    It's called only at line 578. Delete the function and replace call with just `passthru`.

    **Fix:**
    - Delete lines 522-529 (function definition)
    - Line 578: Replace `filter_commit_passthru(passthru)` with `passthru`
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [522, 529],  // Dead function - just returns input
      578,  // Call site - should use passthru directly
    ],
  },
)
