local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Comments state obvious facts that are already clear from method names, types,
    and code structure.

    Examples:
    - "Call persistence to get ACTUAL ID" followed by `policy_id = await self._persistence.set_policy(...)`
    - "Create proposal and get actual database-assigned ID" followed by `proposal_id = await self._persistence.create_policy_proposal(...)`
    - "Generate or use provided UI token" followed by `if ui_token is None: ui_token = generate_ui_token()`

    Problems:
    - Obviously calling persistence (visible in code)
    - Obviously getting IDs (clear from method names and return types)
    - Just restates what's visually apparent
    - If clarification is needed, should explain WHY, not WHAT

    Delete these comments. Method names and code structure are sufficient.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/approvals.py': [319, 346],
      },
      note: 'Lines 319, 346: "Call persistence to get ACTUAL ID", "Create proposal and get actual database-assigned ID"',
      expect_caught_from: [['adgn/src/adgn/agent/approvals.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/server.py': [421, 459],
      },
      note: 'Lines 421, 459: "Generate or use provided UI token", "Health check endpoint"',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/server.py']],
    },
  ],
)
