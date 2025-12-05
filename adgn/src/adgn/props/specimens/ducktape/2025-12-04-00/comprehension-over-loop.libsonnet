local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 221-225 use a for loop to build a dict filtering by condition (v.spec is not None).
    This imperative pattern should be replaced with a dict comprehension for clarity and conciseness:
    return {k: v.spec for k, v in self._mounts.items() if v.spec is not None}
  |||,
  filesToRanges={'adgn/src/adgn/mcp/compositor/server.py': [[221, 225]]},
)
