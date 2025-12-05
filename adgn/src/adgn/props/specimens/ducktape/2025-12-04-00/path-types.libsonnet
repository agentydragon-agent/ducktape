local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    File path parameters should use pathlib.Path instead of str for type safety and cleaner path operations.
    Using Path types enables method chaining (.parent, .name, .exists()) and avoids manual string concatenation.
    Current code mixes str and Path types or unnecessarily converts Path to str.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/gepa/gepa_adapter.py': [[66, 66]]},
      note: 'SnapshotInput.target_files uses set[Path] but other path parameters like specimen_slug are plain str',
      expect_caught_from: [['adgn/src/adgn/props/gepa/gepa_adapter.py']],
    },
    {
      files: {'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[18, 44], [47, 62], [239, 363]]},
      note: 'Functions use list[str] and str for file paths instead of Path objects',
      expect_caught_from: [['adgn/src/adgn/props/cli_app/cmd_build_bundle.py']],
    },
  ],
)
