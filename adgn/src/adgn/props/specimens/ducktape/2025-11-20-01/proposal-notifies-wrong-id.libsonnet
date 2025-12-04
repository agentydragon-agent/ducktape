local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 232-237 define create_proposal that sets new_id = 0 as placeholder, calls
    persistence with that placeholder, and notifies with str(new_id) still as "0".
    The actual database-assigned ID is never retrieved or used.

    Bug: clients receiving the notification get wrong proposal ID (0), notification
    points to non-existent proposal, return value at line 237 also wrong (returns 0
    instead of actual ID), creates data inconsistency between notified and persisted.

    Fix: create_policy_proposal should return actual database-assigned ID, then notify
    and return that ID. Or if persistence doesn't return ID, refactor it to do so or
    query for newly created proposal. Comment at lines 234-235 acknowledges the problem.

    Related to issue 023 about proposal_id type inconsistency.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [232, 237],  // create_proposal using placeholder ID 0
      [234, 235],  // Comment acknowledging the problem
    ],
  },
)
