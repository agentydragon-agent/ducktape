local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Repeated admin_server creation should be a shared fixture.

    Every test creates its own `ApprovalPolicyAdminServer(engine=engine)`. This appears at lines 43, 56, 70, 90, 107, 122, 133, 146.

    Should be a fixture that depends on the `engine` fixture.

    Benefits:
    - DRY principle
    - Consistent setup across tests
    - Easy to modify server configuration
  |||,
  filesToRanges={
    'adgn/tests/agent/test_policy_validation_reload.py': [
      43,
      56,
      70,
      90,
      107,
      122,
      133,
      146,
    ],
  },
)
