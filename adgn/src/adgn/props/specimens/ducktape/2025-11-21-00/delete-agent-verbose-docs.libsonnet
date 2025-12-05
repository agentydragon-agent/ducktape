local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `delete_agent` docstring (lines 796-810) is unnecessarily verbose, restating obvious
    information.

    Summary "Delete an agent and clean up its infrastructure" is clear and sufficient. Elaboration
    "Removes the agent from the registry, closes all running infrastructure, and releases associated
    resources" just expands on "clean up" - implied by deletion. Statement "The agent can no longer
    be accessed after deletion" is what deletion means (like "After you delete a file, the file is
    deleted"). Args section "agent_id: ID of the agent to delete" restates parameter name and
    function name, provides zero new information. Returns section "SimpleOk confirming successful
    deletion" is obvious from return type and function name.

    Only the Raises section (KeyError when agent not found) adds information and should be kept.

    Recommended: Keep only summary line and Raises section (4 lines instead of 15). Focuses on
    essential information, no redundant content, easier to read and maintain.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [796, 810],  // Overly verbose docstring
      [798, 800],  // Redundant elaboration paragraph
      [802, 806],  // Obvious Args and Returns sections
    ],
  },
)
