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

    Option 1: Take Pydantic model, do serialization inside:
    ```python
    def run_policy_source(
        *,
        docker_client: DockerClient,
        source: str,
        input_payload: PolicyRequest,  # ← Type-safe Pydantic model
        image: str | None = None,
        timeout_secs: float | None = None,
    ) -> PolicyResponse:
        # Serialize inside the function
        ctx_json = input_payload.model_dump_json()
        ...
    ```

    Option 2: Take raw string/bytes for true low-level use:
    ```python
    def run_policy_source(
        *,
        docker_client: DockerClient,
        source: str,
        input_json: str,  # ← Raw JSON string
        image: str | None = None,
        timeout_secs: float | None = None,
    ) -> PolicyResponse:
        # Use directly, no conversion
        env = {"POLICY_SRC": source, "POLICY_INPUT": input_json}
        ...
    ```

    **Option 1 is better** because:
    - Type-safe at call sites
    - Validation happens in one place
    - Callers work with domain types, not dicts
    - Easier to test (construct PolicyRequest, not dicts)

    **Problem 2: Questionable split between runner.py and container.py**

    `ContainerPolicyEvaluator` is a 40-line class that just wraps `run_policy_source()`
    with some config storage. This creates two entrypoints for the same operation,
    causing confusion about which to use.

    **Current structure:**
    ```
    runner.py:
      - run_policy_source(dict) -> PolicyResponse  # Low-level function

    container.py:
      - ContainerPolicyEvaluator                   # Thin wrapper class
          - __init__(agent_id, docker, engine, ...)
          - decide(PolicyRequest) -> PolicyResponse
              - Calls run_policy_source(dict)
    ```

    **Call sites:**
    - `approvals.py:310`: Calls `run_policy_source()` directly (self-check/validation)
    - `server.py:178`: Creates `ContainerPolicyEvaluator` for per-agent evaluation

    **The smell:**

    Both the outer wrapper (`ContainerPolicyEvaluator`) and the direct caller
    (`approvals.py`) do Pydantic→dict conversion, suggesting the abstraction layers
    are wrong. Why have two entrypoints to the same operation?

    **The correct approach:**

    Merge into one module with clear responsibilities:

    ```python
    # policy_eval/evaluator.py (or just policy_eval.py)

    @dataclass
    class ContainerPolicyEvaluator:
        """Evaluate policy decisions inside one-off Docker containers."""

        agent_id: AgentID
        docker_client: DockerClient
        engine: ApprovalPolicyEngine
        image: str = field(default_factory=resolve_runtime_image)
        timeout_secs: float = field(
            default_factory=lambda: float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
        )

        async def decide(self, request: PolicyRequest) -> PolicyResponse:
            """Evaluate a policy decision using the current active policy."""
            policy_src, _ver = self.engine.get_policy()
            return self._run_policy(source=policy_src, request=request)

        def self_check(self, source: str) -> None:
            """Validate policy source by running a dummy request."""
            dummy = PolicyRequest(
                name=build_mcp_function(UI_SERVER_NAME, "send_message"),
                arguments={}
            )
            self._run_policy(source=source, request=dummy)

        def _run_policy(
            self, *, source: str, request: PolicyRequest
        ) -> PolicyResponse:
            """Run policy source with a request (internal helper)."""
            # All the Docker container logic here (from current run_policy_source)
            ctx_json = request.model_dump_json()
            cmd = ["python", "-m", "adgn.agent.policy_eval.shim"]
            env = {"POLICY_SRC": source, "POLICY_INPUT": ctx_json, ...}
            # ... container creation, execution, result parsing ...
            return PolicyResponse.model_validate(data)
    ```

    **Why this is better:**

    1. **Single entrypoint**: Only `ContainerPolicyEvaluator` exists
    2. **Type-safe API**: All methods take Pydantic models, not dicts
    3. **Clear responsibilities**:
       - `decide()` - evaluate with active policy
       - `self_check()` - validate policy source
       - `_run_policy()` - internal Docker execution
    4. **No duplication**: Serialization happens in one place (`_run_policy`)
    5. **Better discoverability**: All policy eval in one module
    6. **Easier to test**: Mock the evaluator, not free functions

    **Migration:**

    - Merge `runner.py` into `container.py` (or rename to `evaluator.py`)
    - Make `_run_policy()` private (internal helper)
    - Add `self_check()` method to evaluator
    - Update call sites:
      - `approvals.py`: Call `evaluator.self_check(source)`
      - `server.py`: Already uses `ContainerPolicyEvaluator`

    **When the split WOULD make sense:**

    - If `run_policy_source()` was used by multiple different evaluator types
    - If there was a synchronous and async version sharing the core logic
    - If the low-level function was tested independently in many scenarios

    But currently:
    - Only one evaluator type (container-based)
    - Only one usage pattern (evaluate policy)
    - `run_policy_source()` isn't tested separately

    Therefore: the split adds complexity without benefit.
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
