local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 95-96 in `await_decision` use a two-line pattern: get a value, check if None.
    The walrus operator provides a cleaner one-line solution for this exact pattern.

    Current: `pending = self._pending.get(call_id)` then `if pending is None:`. This is
    verbose (two lines), pollutes scope (pending exists outside if/else), and less Pythonic.

    Replace with: `if (pending := self._pending.get(call_id)) is None:`. Benefits: more
    concise, clearer scope (pending only in else branch where used), idiomatic Python 3.8+
    (PEP 572).

    Note: Line 106 has similar pattern but is correct because pending appears in the
    condition itself, not just the None check.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [95, 96],   // pending = get(); if None pattern that should use walrus
    ],
  },
)
