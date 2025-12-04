local I = import '../../lib.libsonnet';

// iss-030: Inconsistent policy evaluation API layers and dict middle ground

I.issue(
  rationale= |||
    The policy evaluation code has an awkward split between `runner.py` and
    `container.py` with an inconsistent middle layer that takes `dict` instead of
    either parsed Pydantic models or raw strings/bytes.

    **Problem 1: input_payload: dict is an inconsistent middle ground**

    `run_policy_source()` takes `input_payload: dict`, which is neither:
    - A proper Pydantic model (type-safe, validated)
    - Raw bytes/string (unparsed, for true low-level use)

    This forces callers to manually convert Pydantic → dict, duplicating serialization
    logic at call sites.

    **Current implementation (runner.py, lines 16-23):**
    ```python
    def run_policy_source(
        *,
        docker_client: DockerClient,
        source: str,
        input_payload: dict,  # ← Weird middle ground
        image: str | None = None,
        timeout_secs: float | None = None,
    ) -> PolicyResponse:
    ```

    **Callers manually convert Pydantic → dict:**

    In `container.py` (lines 48-56):
    ```python
    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        payload = {"name": policy_input.name, "arguments": policy_input.arguments}
        policy_src, _ver = self._engine.get_policy()
        return run_policy_source(
            docker_client=self._docker,
            source=policy_src,
            input_payload=payload,  # ← Manual dict
            ...
        )
    ```

    In `approvals.py` (lines 310-313):
    ```python
    run_policy_source(
        docker_client=self.docker_client,
        source=source,
        input_payload={"name": build_mcp_function(...), "arguments": {}},  # ← Manual dict
    )
    ```

    **The correct approach:**

    Take a Pydantic `PolicyRequest` model instead of `dict`, and serialize it
    inside the function. This makes call sites type-safe, validates in one place,
    and callers work with domain types rather than dicts.

    **Problem 2: Questionable split between runner.py and container.py**

    `ContainerPolicyEvaluator` is a 40-line wrapper around `run_policy_source()`,
    creating two entrypoints for the same operation. Both the wrapper class and
    direct callers do Pydantic→dict conversion, suggesting wrong abstraction layers.

    **The correct approach:**

    Merge into one module with a single `ContainerPolicyEvaluator` class that has:
    - `decide(request: PolicyRequest)` - evaluate with active policy
    - `self_check(source: str)` - validate policy source
    - `_run_policy(source, request)` - private Docker execution helper

    This provides a single type-safe entrypoint, eliminates duplication, and keeps
    serialization in one place. The current split only makes sense if there were
    multiple evaluator types or usage patterns, which there aren't.
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
