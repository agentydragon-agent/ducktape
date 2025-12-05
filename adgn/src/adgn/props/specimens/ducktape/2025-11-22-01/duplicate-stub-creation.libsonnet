local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    All 7 test functions in test_policy_validation_reload.py duplicate the same
    ApprovalPolicyAdminServerStub creation pattern: open Client context, create stub
    from server and session, call stub method.

    This pattern appears at lines 47, 57, 67, 84, 97, 109, 131. Violates DRY: harder to
    maintain (changes need 7 updates), more verbose (2-3 extra setup lines per test),
    less focused (setup obscures intent).

    Fix: create pytest fixture that returns connected stub via asynccontextmanager or
    function-scoped fixture with explicit cleanup. Eliminates 14+ duplicate lines.
  |||,
  filesToRanges={
    'adgn/tests/agent/test_policy_validation_reload.py': [
      [47, 48],   // Test 1 stub creation
      [57, 58],   // Test 2 stub creation
      [67, 68],   // Test 3 stub creation
      [84, 85],   // Test 4 stub creation
      [97, 98],   // Test 5 stub creation
      [109, 110], // Test 6 stub creation
      [131, 132], // Test 7 stub creation
    ],
  },
)
