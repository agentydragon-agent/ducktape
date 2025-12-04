local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Single-use variable with redundant comment.

    Lines 86-88 in test_policy_validation_reload.py create a variable `new_policy` that is used only once. The comment "Save a policy to persistence" is redundant since the code is self-documenting.

    Should inline: `await persistence.set_policy(engine.agent_id, content="print('from persistence')")`
  |||,
  filesToRanges={
    'adgn/tests/agent/test_policy_validation_reload.py': [[86, 88]],
  },
)
