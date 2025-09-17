local I = import '../../specimens/lib.libsonnet';

// iss-066: Useless docstrings that do not add value
I.issueOneOccurrence(
  rationale=|||
    Remove trivial docstrings that restate what the property name and type already communicate. Keep docstrings only for non-obvious behavior or invariants.
    - In wt/wt/server/gitstatusd_client.py at lines 119–121: `has_dirty_files` docstring restates the obvious; remove or replace with a short note only if there is non-obvious behavior.
    - In wt/wt/server/gitstatusd_client.py at lines 126–127: `has_untracked_files` docstring restates the obvious; remove or replace with a short note only if there is non-obvious behavior.
  |||,
  // properties=['no-useless-docs'],
  gap_note='docstring: for stuff that\'s the "what" a user should know (contract, important caveats). __doc__ acts as "help".\n\ncomment: the "how" — implementation details callers don\'t need; use comments for internal stages/notes, not as external API documentation.',
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[119, 121], [126, 127]],
  },
)
