local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/runtime.py'],
    ['adgn/src/adgn/agent/server/protocol.py'],
  ],
  rationale= |||
    The `approval_policy` field is included BOTH as a direct sibling field in Snapshot
    AND inside the `details.SnapshotDetails` bundle. This is redundant duplication.

    **Current implementation (runtime.py:232, 244-245):**
    ```python
    details = SnapshotDetails(run_state=self.active_run, sampling=sampling, approval_policy=approval_policy)

    return Snapshot(
        v="1.0.0",
        session_state=SessionState(...),
        approval_policy=approval_policy,  # Line 244: As sibling
        details=details,                   # Line 245: Contains approval_policy inside
    )
    ```

    **Snapshot schema (protocol.py:193-200):**
    ```python
    class Snapshot(BaseModel):
        type: Literal["snapshot"] = "snapshot"
        v: str
        session_state: SessionState
        approval_policy: ApprovalPolicyInfo | None = None  # Direct field
        details: SnapshotDetails | None = None              # Contains approval_policy
    ```

    **SnapshotDetails schema (protocol.py:179-190):**
    ```python
    class SnapshotDetails(BaseModel):
        run_state: RunState
        sampling: SamplingSnapshot
        approval_policy: ApprovalPolicyInfo  # Duplicates the sibling field!
    ```

    **Problems:**
    1. **Data duplication**: Same data sent twice in the same response
    2. **Inconsistency risk**: Two copies can drift if one is updated but not the other
    3. **Confusing semantics**: Which is authoritative? The sibling or the one in details?
    4. **Waste**: Larger payloads with redundant data
    5. **Related to issue 014**: This reinforces that the SnapshotDetails bundle is architecturally wrong

    **Why this happened:**
    The comment on line 229 says "Build preferred details bundle when all components are
    present", suggesting this was a migration path. But the old `approval_policy` sibling
    field was never removed, creating duplication.

    **Correct solution (related to issue 014):**
    Delete the SnapshotDetails bundle entirely and keep fields as direct siblings:

    ```python
    return Snapshot(
        v="1.0.0",
        session_state=SessionState(...),
        approval_policy=approval_policy,  # Optional field
        run_state=self.active_run,        # Optional field
        sampling=sampling,                 # Optional field
    )
    ```

    **Alternative (if you must keep the bundle):**
    Remove `approval_policy` from the sibling fields:

    ```python
    return Snapshot(
        v="1.0.0",
        session_state=SessionState(...),
        # approval_policy=approval_policy,  # DELETED - only in details
        details=details,
    )
    ```

    But this is still worse than the direct-sibling approach.

    **Note:** This issue is particularly suspicious because it shows the bundle pattern
    is incomplete/half-migrated. The presence of the sibling field suggests even the
    original author wasn't confident in the bundling approach.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [232, 232],  // SnapshotDetails includes approval_policy
      [244, 245],  // Snapshot has approval_policy as both sibling and in details
    ],
    'adgn/src/adgn/agent/server/protocol.py': [
      [179, 190],  // SnapshotDetails with approval_policy field
      [193, 200],  // Snapshot with both approval_policy sibling and details bundle
    ],
  },
)
