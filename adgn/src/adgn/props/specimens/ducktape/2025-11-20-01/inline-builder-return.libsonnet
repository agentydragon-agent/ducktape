local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 63-67 create MCPInfrastructure instance assigned to builder, then immediately
    use it in return statement to call builder.start(). This single-use intermediate
    variable should be inlined.

    Variable name adds no semantic value beyond class name. Standard pattern: create
    object and call method in one expression. Chaining constructor → method is clear
    and readable. Common Python idiom for builder/factory patterns.

    Inline to: return await MCPInfrastructure(...).start(mcp_config). More concise
    without sacrificing readability. Similar pattern found at runtime/builder.py:74
    and runtime/infrastructure.py:57 - all should be updated consistently.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [63, 67],  // builder extraction and immediate use
    ],
  },
)
