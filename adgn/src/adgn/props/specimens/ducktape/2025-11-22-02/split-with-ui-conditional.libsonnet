local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 70-72 and 84-86 split with_ui conditional logic unnecessarily. First
    block creates ui_bus and connection_manager, then builder.start() executes,
    then second block attaches UI sidecar. These operations are independent and
    could be consolidated.

    **Problem:** Split conditional increases cognitive load and makes control flow
    harder to follow. The two if with_ui blocks could be merged, or consolidated
    entirely by moving ConnectionManager construction inline and creating ui_bus
    only when needed.

    **Fix:** Consolidate into single block after builder.start() by using inline
    conditional for connection_manager and creating ui_bus only in the final if
    block. Eliminates split conditional.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/builder.py': [
      [70, 72],  // First if with_ui block
      [84, 86],  // Second if with_ui block
    ],
  },
)
