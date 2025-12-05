local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Variables abbreviated to save characters without achieving any meaningful line length savings. Full descriptive names improve readability at negligible cost.

    Specific instances:
    - cid → call_id (used throughout agent.py)
    - ocid → original_call_id (lines 555-563)

    The abbreviations save 5-6 characters but don't prevent any line wrapping, so they only reduce clarity.
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [358, 360, 396, 407, 411, [555, 563]]},
)
