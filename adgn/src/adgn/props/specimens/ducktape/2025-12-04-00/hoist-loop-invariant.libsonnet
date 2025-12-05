local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The assertion that eval_batch.trajectories is not None appears inside the loop at line 279
    but is a function-level invariant. It should be moved outside the loop (after line 272)
    since trajectories is either always None or always present for the entire batch.

    Additionally, the loop over components_to_update should be removed entirely since
    there will be exactly one component ("system_prompt"). The code can directly process
    that component without iteration.
  |||,
  filesToRanges={'adgn/src/adgn/props/gepa/gepa_adapter.py': [[274, 300]]},
)
