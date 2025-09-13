local I = import '../../specimen_issues.libsonnet';

// iss-028: No useless docs — remove/rewrite trivial docstrings and historical comments
I.issueOccurrencesFromLines(
  rationale=|||
    Remove or simplify docstrings/comments that restate the obvious or describe merely-historical workflows.
    Keep only documentation that has actual value for current state of the codebase.
    (One particular case: does not restate what's obviousl immediately from source code.)
  |||,
  properties=['no-useless-docs'],
  linesByFile={
    'wt/wt/server/wt_server.py': [[674, 675, 'Remove historical comment (filesystem watching moved); document current state only.']],
    'wt/wt/client/handlers.py': [[5, 'Docstring for `handle_status` restates the obvious; delete.']],
    'wt/wt/shared/github_models.py': [[21, 23, '`is_merged` docstrings restate the obvious; remove or drop property if unused.'], [55, 57, '`is_merged` docstrings restate the obvious; remove or drop property if unused.']],
    'wt/wt/server/gitstatusd_client.py': [[133, 141, '`is_ahead_of_upstream` / `is_behind_upstream` docstrings restate the obvious; remove.']],
  },
)
