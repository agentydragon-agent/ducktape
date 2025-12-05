local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Conditional at lines 169-190 nests the complex branch inside an if, making the code harder to follow.
    The mount.proxy is None case (line 190) is simple and should be handled with early bailout:
    - Check if mount.proxy is None, set InitializingServerEntry, continue to next mount
    - Remove the else branch and un-indent the complex logic
    This reduces nesting depth by one level for the main logic path.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/compositor/server.py': [[169, 190]]},
)
