local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Line 28 defines `_APPROVALS_AND_TOOLS = dedent("").strip()`, which always evaluates to empty
    string `""`. Line 56 includes this in `"\n\n".join([_BASE, _APPROVALS_AND_TOOLS, _OUTPUT_STYLE, _HOUSE_RULES])`.

    This is dead code: `dedent("").strip()` performs no-op transformations on empty string, and
    joining with empty element adds no content but suggests placeholder "in case we need it later".

    Delete the constant definition (line 28) and remove it from the join list (line 56). If content
    is truly planned for later, add explicit TODO comment with owner and conditionally insert into
    join only when non-empty.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/system_message.py': [
      [28, 28],   // dedent("").strip() creates empty constant
      [56, 56],   // Empty constant included in join
    ],
  },
)
