local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `create_agent_compositor` function creates intermediate variables `policy_server`
    (line 48) and `approvals_server` (lines 53-57) that are used exactly once in the
    immediately following `mount_inproc()` call. These add no clarity and should be inlined.

    Problems: (1) Unnecessary binding - variables never referenced again. (2) Name pollution -
    add no semantic value. (3) Cognitive load - reader tracks "what is this for?". (4) Not
    used in logging or error handling. (5) False complexity - suggests variable might be
    used later.

    Why they exist: Likely habit from longer functions where variables were reused, possibly
    for debugging (but not used in logging), or copy-pasted from code where needed.

    Inline the constructors directly into `mount_inproc()` calls. Server types are clear from
    class names, construction is straightforward, and values are used once. Python idiom
    encourages inline construction for single-use values.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      [47, 50],   // Unnecessary policy_server variable
      [52, 59],   // Unnecessary approvals_server variable
    ],
  },
)
