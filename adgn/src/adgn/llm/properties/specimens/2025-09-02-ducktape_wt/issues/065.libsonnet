local I = import '../../specimens/lib.libsonnet';

// iss-065: Remove unreachable IndexError catches after MIN_GIT_REPO_FIELDS gate
I.issueOneOccurrence(
  rationale='After the response boundary validates `len(fields) >= MIN_GIT_REPO_FIELDS`, the later internal helper parsers\' IndexError catches and default-substitution branches are superfluous and effectively dead; remove those unreachable defensive branches and use hard guards so invariants are explicit. Add an explicit invariant comment at the single gating location explaining the post-gate guarantee (e.g., "after this point, fields has at least MIN_GIT_REPO_FIELDS entries").',
  // properties=['scoped-try-except', 'no-dead-code'],
  gap_note='GAP: Bundle and document the gating invariant (e.g., "after this point, fields has at least MIN_GIT_REPO_FIELDS entries"). This points in the direction of a general heuristic: prefer explicit contract gates and avoid re-checking/catching individually in helpers.',
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[294, 355]],
  },
)
