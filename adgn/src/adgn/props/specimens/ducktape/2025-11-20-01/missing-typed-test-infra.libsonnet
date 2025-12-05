local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Approval policy tests lack typed test infrastructure (server stubs + fixture factories) used by other MCP components.

    Tests directly access private `._mcp_server` internals for tool calls and resource reads instead of using typed server stubs. Multiple tests in test_policy_resources.py use raw `._mcp_server.call_tool()` and `._mcp_server.read_resource()` methods. Tests in test_policy_validation_reload.py access private `_mcp_server._tools` dict directly with pattern `await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(...))`.

    Tests also create server instances in class-level fixtures (test_policy_resources.py lines 53-61) instead of using shared fixtures in conftest.py or fixture factories.

    Other MCP tests (exec, editor, chat) use typed stub classes for type safety (see exec_stubs.py pattern). Should create `adgn/src/adgn/mcp/testing/approval_policy_stubs.py` with:
    - `ApprovalPolicyServerStub` (reader)
    - `ApprovalPolicyProposerServerStub`
    - `ApprovalPolicyAdminServerStub`

    Typed methods provide IDE completion, type checking for tool arguments/returns, more ergonomic API, and avoid accessing private internals.

    Should also use shared fixtures or fixture factories for server setup to reduce duplication and ensure consistency across test files.
  |||,
  filesToRanges={
    'adgn/tests/mcp/approval_policy/test_policy_resources.py': [
      [53, 61],
      70,
      [82, 90],
      103,
      [130, 138],
      141,
      [158, 166],
      [181, 197],
      [203, 209],
      [227, 244],
      [256, 263],
      [270, 285],
      [300, 305],
      [312, 315],
      [325, 328],
      [366, 372],
      [381, 384],
    ],
    'adgn/tests/agent/test_policy_validation_reload.py': [
      46,
      59,
      [73, 75],
      96,
      111,
      126,
      149,
    ],
  },
  expect_caught_from=[
    ['adgn/tests/mcp/approval_policy/test_policy_resources.py'],
    ['adgn/tests/agent/test_policy_validation_reload.py'],
  ],
)
