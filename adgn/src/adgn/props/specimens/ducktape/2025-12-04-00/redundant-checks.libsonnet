local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Redundant checks and guards that serve no purpose and can be removed. These include checking the same condition twice, redundant None checks with isinstance, and redundant type validation.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[224, 235]]},
      note: 'Checks for bundle metadata twice - first at line 226 with dict.get(), then at line 233 with validated model',
      expect_caught_from: [['adgn/src/adgn/props/cli_app/cmd_build_bundle.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/models.py': [[304, 305]]},
      note: 'Checks both "ctx is None OR not isinstance(ctx, ...)" - isinstance already handles None',
      expect_caught_from: [['adgn/src/adgn/props/grader/models.py']],
    },
    {
      files: {'adgn/src/adgn/agent/agent.py': [87]},
      note: 'Redundant isinstance check: "if not isinstance(call_id, str) or not call_id" - second condition is sufficient',
      expect_caught_from: [['adgn/src/adgn/agent/agent.py']],
    },
  ],
)
