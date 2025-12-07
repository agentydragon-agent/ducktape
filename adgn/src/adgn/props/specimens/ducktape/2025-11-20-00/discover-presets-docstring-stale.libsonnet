local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    discover_presets docstring (lines 60-63) references DEFAULT_PRESETS_DIRS, but this constant
    doesn't exist anywhere in the code - the implementation only checks env_dir and
    _xdg_presets_dir() (lines 66-70). The docstring is misleading about the actual search order
    and available configuration.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [[60, 63]],
  },
)
