local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/runtime.py'],
    ['adgn/src/adgn/agent/server/protocol.py'],
  ],
  rationale= |||
    The `approval_policy` field appears BOTH as a direct sibling in Snapshot (protocol.py:199)
    AND inside the `details.SnapshotDetails` bundle (protocol.py:188). Construction in
    runtime.py:232, 244-245 passes `approval_policy` to SnapshotDetails and also assigns it
    as a Snapshot sibling.

    Problems: (1) Data duplication - same data sent twice. (2) Inconsistency risk - two copies
    can drift. (3) Confusing semantics - which is authoritative? (4) Larger payloads.
    (5) Related to issue 014 - reinforces that SnapshotDetails bundle is architecturally wrong.

    Comment on line 229 says "Build preferred details bundle when all components are present",
    suggesting migration path. Old `approval_policy` sibling was never removed, creating duplication.

    Correct solution: Delete SnapshotDetails bundle entirely and keep fields as direct siblings.
    Alternative (if bundle must stay): Remove `approval_policy` from sibling fields. But
    direct-sibling approach is cleaner.
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
