local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 151-155 in cluster_unknowns.py use unnecessary intermediate variables that should be inlined for conciseness.

    The code builds a list of tasks using a loop with two trivial single-use variables:
    - `out_spec = root / spec` (line 153) - only used once on the next line
    - `tasks = []` then `.append()` in loop (lines 151, 154) - should be a list comprehension

    These can be inlined into a single line using `asyncio.gather()` with a generator expression:
    ```python
    await asyncio.gather(*(_cluster_snapshot(items, root / spec, model) for spec, items in by_spec.items()))
    ```

    This eliminates the intermediate variables and makes the parallel execution pattern more evident.
  |||,
  filesToRanges={'adgn/src/adgn/props/cluster_unknowns.py': [[151, 155]]},
)
