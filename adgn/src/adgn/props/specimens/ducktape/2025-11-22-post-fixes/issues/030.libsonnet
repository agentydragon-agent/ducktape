local I = import '../../specimens/lib.libsonnet';

// iss-030: Inconsistent policy evaluation API layers and dict middle ground

I.issueOneOccurrence(
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
  properties=['consistent-abstraction-layers', 'avoid-unnecessary-indirection', 'type-safe-apis'],
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [16, 23],  // input_payload: dict is weird middle ground
      [1, 93],   // Whole file could be merged into container.py
    ],
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [17, 46],  // ContainerPolicyEvaluator is thin wrapper
      [48, 56],  // Manual Pydantic → dict conversion
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [310, 313], // Direct call to run_policy_source with manual dict
    ],
  },
  gap_note= |||
    This finding illustrates **"consistent-abstraction-layers"**: APIs should work
    with consistent types at each layer. Don't have a middle layer that takes `dict`
    when the layer above works with Pydantic models and the layer below serializes
    to JSON.

    Principle: each abstraction layer should have a clear contract:
    - **High level**: Domain types (Pydantic models, dataclasses)
    - **Low level**: Primitive types (str, bytes, int)
    - **Don't mix**: `dict` is neither high-level (no validation) nor low-level (already parsed)

    When `dict` parameters are appropriate:
    - Truly dynamic data (plugin configs, user metadata)
    - Interfacing with untyped external systems
    - Performance-critical paths where validation is separate

    When to avoid `dict` parameters:
    - You have a Pydantic model that describes the shape
    - Callers are constructing dicts from models (they should pass the model)
    - The function immediately serializes to JSON (take the model, serialize inside)

    Related to **"avoid-unnecessary-indirection"**: don't split code into multiple
    modules/classes when one would suffice. Ask: does this split provide value?
    - Multiple implementations? → Split makes sense
    - Shared by many callers? → Split makes sense
    - Different lifecycles? → Split makes sense
    - Just one thin wrapper? → Merge it

    Related to **"type-safe-apis"**: prefer Pydantic models over dicts in function
    signatures. The type system can't help with `dict[str, Any]`, but it can validate
    `PolicyRequest`.

    When considering a split:
    1. Count actual vs potential users (1 wrapper class isn't "reuse")
    2. Check if the split introduces conversion layers (Pydantic → dict → JSON)
    3. Look for duplicated logic at call sites (manual dict construction)
    4. Verify the abstraction has clear benefits (not just "separation of concerns")
  |||,
)
