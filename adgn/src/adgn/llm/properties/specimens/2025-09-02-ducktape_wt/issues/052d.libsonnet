local I = import '../../specimens/lib.libsonnet';

// iss-052d: Inline one-off entry-point iterator
I.issueOneOccurrence(
  rationale='Inline the entry-point iterator instead of assigning to a one-off variable `eps` to reduce noise. Suggested change: replace `eps = md.entry_points().select(group=ENTRYPOINT_GROUP); for ep in eps: ...` with `for ep in md.entry_points().select(group=ENTRYPOINT_GROUP): ...`.',
  // properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/plugins.py': [[56, 58]],
  },
)
