local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 42 and 159 set instructions parameters when creating test MCP servers (NotifyingFastMCP), but these instructions values are never referenced, asserted on, or otherwise used in the test logic. They're immaterial fluff that should be removed.

    Test servers should only set parameters that are relevant to what's being tested. Since these tests are about notification flow (ResourceUpdated broadcasts, buffering, etc.), the instructions content is irrelevant.
  |||,
  filesToRanges={'adgn/tests/agent/test_mcp_notifications_flow.py': [42, 159]},
)
