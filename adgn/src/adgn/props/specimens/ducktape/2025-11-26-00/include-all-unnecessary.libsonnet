local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 719 creates `include_all = args.stage_all`, then uses it throughout. This
    variable adds no value - just use `args.stage_all` directly.

    **Occurrences of include_all:**
    - Line 719: Definition
    - Line 728: `_stage_all_if_requested(repo, include_all)`
    - Line 733: `get_commit_diff(repo, include_all, previous_message)`
    - Line 753: `build_cache_key(..., include_all=include_all, ...)`

    **Fix:** Delete line 719 and replace all `include_all` uses with `args.stage_all`.

    **Benefits:**
    1. Fewer variables to track
    2. Clear where the value comes from (args)
    3. One less line of code
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      719,  // Unnecessary variable - just use args.stage_all
      728,  // Call site
      733,  // Call site
      753,  // Call site
    ],
  },
)
