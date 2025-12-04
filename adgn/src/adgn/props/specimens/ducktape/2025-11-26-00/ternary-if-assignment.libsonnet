local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 230-232 in runtime.py use an imperative if-statement to conditionally assign
    `details`, when a ternary expression would be clearer and more concise.

    **Current pattern:**
    ```
    details = None
    if (condition):
        details = SnapshotDetails(...)
    ```

    **Better:** Use ternary operator for conditional assignment:
    ```
    details = SnapshotDetails(...) if condition else None
    ```

    This is more concise and clearly expresses that `details` is conditionally assigned
    based on a single condition.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [230, 232],  // Imperative if-assignment
    ],
  },
)
