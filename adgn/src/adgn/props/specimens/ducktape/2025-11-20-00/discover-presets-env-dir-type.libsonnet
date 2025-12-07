local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    discover_presets env_dir parameter is typed as str | None but is immediately converted to
    Path(env_dir) on line 68. It should be typed as Path | None to avoid the unnecessary
    conversion and make the API clearer.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [[59, 59], [68, 68]],
  },
)
