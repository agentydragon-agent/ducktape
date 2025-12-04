local I = import '../../lib.libsonnet';

// Merged: assign-then-test-no-walrus, builder-var-missing-walrus
// Both describe assign-and-check patterns that should use walrus operator

I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/mcp_bridge/auth.py'], ['adgn/src/adgn/agent/mcp_bridge/server.py']],
  rationale= |||
    Multiple locations assign a variable and immediately test it, where the walrus
    operator (:=) would combine assignment and conditional test more idiomatically.

    **Pattern 1: HTTP header extraction with check** (auth.py:75-76, 113-114, 144-148):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(...)

    Should use: if not (auth_header := request.headers.get("Authorization")):

    env_token = os.environ.get("ADGN_UI_TOKEN")
    if env_token:
        return env_token

    Should use: if env_token := os.environ.get("ADGN_UI_TOKEN"):

    **Pattern 2: Single-use builder variable** (server.py:85-89):
    builder = MCPInfrastructure(
        agent_id=agent_id,
        persistence=persistence,
        docker_client=docker_client,
        initial_policy=initial_policy
    )
    return await builder.start(mcp_config)

    Should inline: return await MCPInfrastructure(...).start(mcp_config)

    Or if clarity matters, use walrus in await:
    return await (builder := MCPInfrastructure(...)).start(mcp_config)

    **Pattern 3: Get agent and check** (server.py:172-173):
    agent = self._agents[agent_id].agent
    if agent is None:
        raise KeyError(...)

    Should use: if (agent := self._agents[agent_id].agent) is None:

    Benefits of walrus operator (PEP 572):
    - More concise: one line instead of two
    - Clear intent: we're testing the retrieved value
    - Modern Python idiom (introduced in Python 3.8)
    - Variable scope is explicit: only exists where needed

    Benefits of inlining single-use variables:
    - Reduces temporary variables that add no semantic value
    - Makes data flow more obvious
    - Less cognitive overhead (fewer names to track)
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [75, 76],    // TokenAuthMiddleware.dispatch(): auth_header + if
      [113, 114],  // generate_ui_token(): env_token + if
      [144, 148],  // UITokenAuthMiddleware.__call__(): auth_header + if
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [85, 89],    // Single-use builder variable
      [172, 173],  // agent extraction and None check
    ],
  },
)
