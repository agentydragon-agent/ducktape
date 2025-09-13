local I = import '../../specimen_issues.libsonnet';

// iss-069: _compute_teleport_target should return Path not str
I.issueOneOccurrence(
  rationale='`_compute_teleport_target` currently returns a string; prefer returning a Path to avoid downstream `str(...)` conversions and keep internal models as Path types. Suggested change: return Path and update callers to accept Path or explicitly convert at the boundary.',
  properties=['pathlib'],
  gap_note='GAP: Commit to a single type/contract across layers; avoid mixed str/Path states; document where conversion to/from str occurs so callers know the boundary.',
  filesToRanges={
    'wt/wt/server/wt_server.py': [[2369, 2382]],
  },
)
