local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 114 in presets.py hides errors when requesting an unknown preset name:
    `preset = presets.get(preset_name or "default") or presets["default"]`. This fallback chain silently
    returns the default preset if the requested name doesn't exist, making typos or missing presets hard
    to detect. The function should raise a KeyError when an unknown preset is requested. The signature
    should default `preset_name` to "default" (`preset_name: str = "default"`), then directly access
    `presets[preset_name]` without catching KeyError.
  |||,
  filesToRanges={'adgn/src/adgn/agent/presets.py': [114]},
)
