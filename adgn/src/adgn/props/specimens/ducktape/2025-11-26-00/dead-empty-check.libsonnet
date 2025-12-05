local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 185-186 check `if not batch.resources: return None`. This is dead code
    because `batch.resources` is a dict, and the next check (lines 189-193) already
    filters for servers with actual updates, returning None if the filtered dict is
    empty.

    The behavior is identical whether `batch.resources` is an empty dict or just
    doesn't have any entries with updates. The early return for empty dict adds no value.

    **Fix:** Delete lines 185-186. The filtering logic already handles the "no updates" case.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/reducer.py': [
      [185, 186],  // Dead code - unnecessary empty check
    ],
  },
)
