local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 29-30 contain useless comments documenting historical implementation details.

    The comments explain that gateway_client parameter is "no longer used" and describe
    internal implementation changes. Historical notes and internal implementation rationale
    don't help readers understand current behavior. Delete them.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/setup.py': [[29, 30]],
  },
)
