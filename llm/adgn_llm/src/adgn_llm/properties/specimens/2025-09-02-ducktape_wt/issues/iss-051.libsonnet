local I = import '../../specimen_issues.libsonnet';

// iss-051: Inline trivial pass-throughs and one-off result variable
I.issueOccurrencesFromLines(
  rationale='Inline trivial pass-through helpers and single-use temporary variables at call sites to reduce indirection.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  linesByFile={
    'wt/wt/server/wt_server.py': [[1580, 1582, '`_create_success_response` is a trivial pass-through; inline Response(result=..., id=request.id) at callers.'], [2168, 2169, "Inline one-off 'result' temporary: replace with direct call to _create_success_response(WorktreeListResult(...), request.id)."]],
  },
)
