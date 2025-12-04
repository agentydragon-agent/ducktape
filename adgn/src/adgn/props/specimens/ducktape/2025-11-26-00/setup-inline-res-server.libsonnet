local I = import '../../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    Line 31 creates unnecessary res_server intermediate variable.

    The variable is assigned and immediately passed to mount_inproc on the next line.
    Inline the make_resources_server() call directly into the mount_inproc() call.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/setup.py': [31],
  },
)
