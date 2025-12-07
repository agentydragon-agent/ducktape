local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    ConnectionManager._send_direct_all is never called (ripgrep finds only the definition).
    Dead code should be removed.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [[187, 196]],
  },
)
