local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    GEPA optimization repeatedly hydrates the same snapshots, causing ~200 redundant tar extractions and file discoveries during a typical optimization run.

    **The inefficiency:**

    Dataset loading (`load_datasets()`, lines 308-334) hydrates each snapshot once to extract metadata, then closes the hydrated context:

    ```python
    async with registry.load_and_hydrate(slug) as hydrated:
        return SnapshotInput(slug=slug, target_files=..., ...)
    # Hydrated snapshot deleted here when context exits
    ```

    During optimization, each evaluation re-hydrates from scratch (`_evaluate_one_specimen()`, line 195):

    ```python
    async def _evaluate_one_specimen(self, specimen_input: SnapshotInput, ...):
        async with self.registry.load_and_hydrate(slug) as hydrated:
            # Run critic with fresh hydration
    ```

    **Performance impact:**

    With 5-10 unique snapshots and max_metric_calls=200:
    - Initial loading: 5-10 hydrations (~5-10 seconds)
    - Optimization evaluations: ~200 hydrations (~200-400 seconds total)
    - Each hydration: tar extraction, JSON parsing, file discovery (~1-2 seconds)
    - Same snapshot hydrated 20-40 times throughout the run

    **Why this matters:**

    Snapshots are mounted read-only to Docker containers, so the hydrated directories could be reused safely. The issue is architectural:
    - `SnapshotInput` stores only metadata (slug, target_files list, ground truth issues)
    - `HydratedSnapshot` objects are created and destroyed per-evaluation
    - No mechanism to keep snapshots hydrated throughout the GEPA run

    **Potential fix:**

    Keep `HydratedSnapshot` objects alive throughout GEPA optimization:
    - Load and hydrate snapshots once at start
    - Pass `HydratedSnapshot` references through the evaluation pipeline (not just metadata)
    - Reuse the same hydrated directories for all critic/grader runs
    - Clean up only at the end of GEPA run

    This would reduce ~200 hydrations to ~10, saving 3-6 minutes per optimization run.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/gepa/gepa_adapter.py': [
      [308, 334],  // load_datasets() - hydrates once, extracts metadata, closes context
      195,         // _evaluate_one_specimen() - re-hydrates for each evaluation
      256,         // _evaluate_async() - calls _evaluate_one_specimen repeatedly
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/props/gepa/gepa_adapter.py'],  // See hydration pattern, recognize redundancy across optimization loop
  ],
)
