local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Silent ignoring of invalid configuration should be replaced with explicit validation.
    When receiving structured inputs, code should assert expected values rather than
    silently skipping unknown options. This catches configuration errors early.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/gepa/gepa_adapter.py': [[274, 276]]},
      note: 'Silent continue for component != "system_prompt" should assert that components_to_update contains only "system_prompt"',
      expect_caught_from: [['adgn/src/adgn/props/gepa/gepa_adapter.py']],
    },
    {
      files: {'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[220, 221]]},
      note: 'yaml.safe_load() fallback "or {}" suppresses None result which should be an error',
      expect_caught_from: [['adgn/src/adgn/props/cli_app/cmd_build_bundle.py']],
    },
  ],
)
