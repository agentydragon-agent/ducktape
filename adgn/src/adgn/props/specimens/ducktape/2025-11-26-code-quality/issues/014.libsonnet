local I = import '../../specimens/lib.libsonnet';

// iss-014: Use ternary for details assignment; suspicious all-or-nothing bundling

I.issueOneOccurrence(
  rationale= |||
    The code uses an imperative if-statement to conditionally assign `details`, when a
    ternary expression would be clearer. More importantly, the all-or-nothing bundling
    of details is architecturally suspicious.

    **Current implementation (runtime.py:230-232):**
    ```python
    # Build preferred details bundle when all components are present
    details = None
    if (self.active_run is not None) and (sampling is not None) and (approval_policy is not None):
        details = SnapshotDetails(run_state=self.active_run, sampling=sampling, approval_policy=approval_policy)
    ```

    **Issue 1: Imperative assignment instead of ternary**

    This is a simple conditional assignment that should use a ternary operator:

    ```python
    details = (
        SnapshotDetails(run_state=self.active_run, sampling=sampling, approval_policy=approval_policy)
        if self.active_run and sampling and approval_policy
        else None
    )
    ```

    **Issue 2: Suspicious all-or-nothing bundling**

    The code only includes `details` if ALL three components (run_state, sampling, approval_policy)
    are present. If any one is missing, the entire details object is omitted.

    **Why this is suspicious:**
    - Each component (run_state, sampling, approval_policy) has independent value
    - Why should missing `sampling` prevent including `run_state` and `approval_policy`?
    - This creates an artificial coupling between unrelated data
    - Consumers likely want partial data rather than all-or-nothing

    **Likely correct solution:**

    Instead of the monolithic `SnapshotDetails` bundle, include components individually:

    ```python
    return Snapshot(
        v="1.0.0",
        session_state=SessionState(...),
        run_state=self.active_run,           # Optional field
        sampling=sampling,                    # Optional field
        approval_policy=approval_policy,      # Optional field
        # ... other fields
    )
    ```

    Each field is independently optional. Consumers can handle partial data gracefully.

    **Benefits:**
    1. No artificial coupling between unrelated data
    2. More flexible - clients get whatever data is available
    3. Clearer semantics - each field has its own optionality
    4. No need for wrapper object that only exists for bundling

    **If you must keep the bundle:**
    At minimum use the ternary, and consider making SnapshotDetails fields optional:
    ```python
    details = SnapshotDetails(
        run_state=self.active_run,
        sampling=sampling,
        approval_policy=approval_policy,
    )
    ```
    where SnapshotDetails has all optional fields.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [230, 232],  // Imperative if-assignment and all-or-nothing bundling
    ],
  },
)
