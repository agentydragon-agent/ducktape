local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 211-220 define notify_proposal_change with str signature, but all three callers
    (lines 236, 253, 258) have int proposal_id and must explicitly convert with str().
    This indicates wrong method signature.

    Problem: all callers (create_proposal line 239, approve_proposal line 239, reject_proposal
    line 255) have proposal_id as int in their signatures, persistence layer likely uses
    int, URI formatting at line 217 works fine with int (f-string converts automatically),
    unnecessary conversions add cognitive load.

    Change notify_proposal_change signature to accept int instead of str. Callers can then
    pass int directly without conversion. Benefits: eliminates unnecessary conversions,
    makes type consistency clear, aligns with persistence layer.

    Related to issue 022 about using wrong ID in create_proposal.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [211, 220],  // notify_proposal_change method with str signature
      [217, 217],  // f-string that would work fine with int
      [236, 236],  // Caller converting int to str
      [253, 253],  // Caller converting int to str
      [258, 258],  // Caller converting int to str
    ],
  },
)
