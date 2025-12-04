local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    ApprovalHub maintains two parallel dicts keyed by call_id (lines 75-78): `_futures` and
    `_requests`. They must be kept in sync manually, which is error-prone.

    **Evidence of parallel management:**
    - Line 94: `self._requests[call_id] = request`
    - Line 98: `self._futures[call_id] = fut`
    - Lines 104-105: both dicts popped together
    - Lines 95-96: checking futures but not requests (asymmetry suggests potential bugs)

    **Why parallel dicts are problematic:**
    - Synchronization burden: must keep both dicts in sync manually
    - Error-prone: easy to update one dict and forget the other
    - Unclear lifecycle: not obvious entries come and go together
    - No type safety: can't enforce both dicts have same keys

    **Fix:** Create a `PendingApproval` dataclass with `request` and `future` fields, use a
    single `_pending: dict[str, PendingApproval]`. Update methods to work with the unified
    structure. The `pending` property (lines 111-114) extracts requests from dataclass entries.
    Benefits: single source of truth, impossible to have mismatched state, type-safe, clearer
    lifecycle, easier to extend.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [75, 78],   // Two parallel dicts definition
      [94, 94],   // _requests assignment
      [98, 98],   // _futures assignment
      [104, 105], // Both dicts popped together
      [111, 114], // pending property returning _requests
    ],
  },
)
