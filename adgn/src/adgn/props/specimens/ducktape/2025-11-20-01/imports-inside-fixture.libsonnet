local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Imports are placed inside a fixture function instead of at module top level.

    In test_policy_resources.py lines 35-37, the fixture `engine` contains imports:
    - `from fastmcp.mcp_config import MCPConfig`
    - `from adgn.agent.persist import AgentMetadata`

    This violates PEP 8 and makes dependencies unclear. Move these imports to the top of the module with other imports.
  |||,
  filesToRanges={
    'adgn/tests/mcp/approval_policy/test_policy_resources.py': [[35, 37]],
  },
)
