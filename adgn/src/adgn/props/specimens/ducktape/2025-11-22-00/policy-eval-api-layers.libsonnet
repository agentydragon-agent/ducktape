local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The policy evaluation code has an awkward split between `runner.py` and `container.py`
    with an inconsistent middle layer.

    Problem 1: `run_policy_source()` (runner.py:16-23) takes `input_payload: dict`, which is
    neither a Pydantic model (type-safe, validated) nor raw bytes/string (unparsed). This
    forces callers (container.py:48-56, approvals.py:310-313) to manually convert Pydantic →
    dict at each call site, duplicating serialization logic.

    Correct approach: Take a Pydantic `PolicyRequest` model and serialize inside the function.
    Makes call sites type-safe, validates in one place, callers work with domain types.

    Problem 2: `ContainerPolicyEvaluator` (container.py:17-46) is a 40-line wrapper around
    `run_policy_source()`, creating two entrypoints. Both the wrapper and direct callers do
    Pydantic→dict conversion, suggesting wrong abstraction layers.

    Correct approach: Merge into one module with single `ContainerPolicyEvaluator` class:
    `decide(request)` evaluates with active policy, `self_check(source)` validates policy,
    `_run_policy(source, request)` private Docker helper. Single type-safe entrypoint,
    eliminates duplication, keeps serialization in one place.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [16, 23],  // input_payload: dict is weird middle ground
      [1, 85],   // Whole file could be merged into container.py
    ],
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [17, 46],  // ContainerPolicyEvaluator is thin wrapper
      [48, 56],  // Manual Pydantic → dict conversion
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [310, 313], // Direct call to run_policy_source with manual dict
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/policy_eval/runner.py'],
    ['adgn/src/adgn/agent/policy_eval/container.py'],
    ['adgn/src/adgn/agent/approvals.py'],
  ],
)
