local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `cmd_build_bundle` function (lines 335-363) uses pygit2 to create filtered
    commits and tags for snapshot bundles, but doesn't return the mapping of tag names
    to commit SHAs that it creates. The function has no return value.

    This forces callers to either:
    1. Write placeholder commit SHAs and manually update them later
    2. Query the bundle post-hoc using `git bundle list-heads`

    The function calls `_build_bundle_internal` which creates the commits and tags.
    That commit information should be captured and returned to callers for automatic
    snapshots.yaml updates.
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[335, 363]]},
)
