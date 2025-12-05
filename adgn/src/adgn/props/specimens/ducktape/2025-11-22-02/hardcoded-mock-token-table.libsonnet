local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 60-63 define TOKEN_TABLE with hardcoded mock data: `{"human-token-123": ...,
    "agent-token-abc": ...}`. The comment "In production, this would be a database lookup
    or external service" indicates temporary/mock code.

    The codebase already has a real implementation: TokenMapping class in
    adgn/src/adgn/agent/mcp_bridge/auth.py (lines 24-58) reads token mappings from JSON files
    with proper error handling (FileNotFoundError, ValueError), reload() method, and get_agent_id()
    lookups.

    TOKEN_TABLE should use a similar file-based approach extended to support both human and agent
    tokens with their metadata (role, agent_id). Replace hardcoded mock data with a configuration
    class that parses JSON/YAML into TokenInfo objects using Pydantic. Update tests to use fixture
    files instead of patching the global.

    Could unify with TokenMapping for a single token configuration file serving both purposes.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [60, 63],  // Hardcoded TOKEN_TABLE with mock data
    ],
  },
)
