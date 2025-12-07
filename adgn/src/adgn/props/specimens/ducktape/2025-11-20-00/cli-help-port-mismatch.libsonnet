local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The top-level CLI help text (lines 6-10) shows a usage example with `--port 8080`, but the
    actual serve command defines `--mcp-port` (line 64) and `--ui-port` (line 65) options instead.
    There is no `--port` option, so following the documented example causes an "no such option"
    error. The help text and actual CLI arguments are inconsistent.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [[10, 10], [64, 65]],
  },
)
