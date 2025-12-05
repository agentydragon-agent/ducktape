local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 91 in presets.py silently hides preset name collisions with `if name not in out:`. When the
    same preset name exists in multiple directories, only the first one is kept and subsequent ones are
    silently ignored. This makes it unclear which preset is actually loaded and can lead to confusion.
    Either raise an error on collision (strict mode) or remove the conditional and allow later directories
    to overwrite earlier ones (simple precedence).
  |||,
  filesToRanges={'adgn/src/adgn/agent/presets.py': [91]},
)
