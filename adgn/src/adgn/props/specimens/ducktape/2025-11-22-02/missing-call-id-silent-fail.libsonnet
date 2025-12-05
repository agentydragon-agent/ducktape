local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Both `resolve()` and `await_decision()` silently handle missing call_ids instead of failing fast.

    Problem 1 (lines 142-148): `resolve()` uses `pop(call_id, None)` which swallows missing call_ids AND still sends notification even though nothing changed. Should use direct dict access (`self._pending[call_id]`) to raise KeyError on missing entries.

    Problem 2 (lines 131-137): `await_decision()` uses `.get(call_id)` and auto-creates new pending approval if missing. Unclear if intentional for first-time calls or if it should raise on truly missing entries.

    Use direct dict access to surface errors immediately rather than silently swallowing them. Only notify when state actually changes.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [142, 148],  // resolve() with pop(call_id, None)
      [131, 137],  // await_decision() with get() fallback
    ],
  },
)
