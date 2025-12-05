local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 230-232 in runtime.py only include `details` if ALL three components
    (run_state, sampling, approval_policy) are present. If any one is missing,
    the entire details object is omitted.

    **Why this is suspicious:**
    - Each component (run_state, sampling, approval_policy) has independent value
    - Why should missing `sampling` prevent including `run_state` and `approval_policy`?
    - This creates artificial coupling between unrelated data
    - Consumers likely want partial data rather than all-or-nothing

    **Likely correct solution:**
    Include components individually in the Snapshot as optional fields, rather than
    bundling them in a monolithic SnapshotDetails object:
    ```
    return Snapshot(
        ...,
        run_state=self.active_run,      # Optional
        sampling=sampling,               # Optional
        approval_policy=approval_policy, # Optional
    )
    ```

    This eliminates artificial coupling and allows clients to handle partial data
    gracefully. Each field has independent optionality rather than forced all-or-nothing.

    **Alternative:** If you must keep the bundle, make SnapshotDetails fields optional
    so the object can be constructed with partial data.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [230, 232],  // All-or-nothing bundling logic
    ],
  },
)
