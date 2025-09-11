local I = import '../../specimen_issues.libsonnet';

  // iss-012b: Forbid dynamic attribute access (presets by value)
  I.issueOneOccurrence(
    id='iss-012b',
    rationale='Pass presets by value (`ConfigPresets.FOO`) instead of by name and `getattr`.',
    properties=['forbid-dynamic-attrs'],
    filesToRanges={
      'wt/tests/config_factory.py': [[45, 46], 128],
    },
    gap_note= |||
     This does use bad unnecessary dynamic attribute access, but the deeper issue is that this name-based pattern is brittle and there's an easily available better alternative.
     With value-based presets, this code path is unnecessary no name lookup or error-name formatting needed.
     Prefer value-based API and delete this path.
     Avoid string→getattr→constant-dict indirection.
     Instead:
     - Pass the constant directly (`PRESET = "preset"`), or
     - Have the constant hold the config object itself (`PRESET = Preset(...)`).
  |||,
  )
