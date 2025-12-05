local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 370 contains a default parameter value (reflection_model: str = "gpt-4o") in optimize_with_gepa. The function is called from a CLI entrypoint that already provides the default, creating layered defaults without clear design intent. Defaults should exist at a single layer (preferably the CLI/entrypoint level) to avoid confusion about which default applies.
  |||,
  filesToRanges={'adgn/src/adgn/props/gepa/gepa_adapter.py': [370]},
)
