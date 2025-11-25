local I = import '../../specimens/lib.libsonnet';

// iss-029: ContainerPolicyEvaluator should be dataclass and remove redundant checks

I.issueOneOccurrence(
  rationale= |||
    The `ContainerPolicyEvaluator` class has multiple issues:

    **Problem 1: Manual class instead of dataclass**

    The class has simple field initialization with no special logic, making it a
    perfect candidate for `@dataclass`. Using a manual `__init__` is verbose and
    adds no value.

    **Current implementation (container.py, lines 17-46):**
    ```python
    class ContainerPolicyEvaluator:
        """Evaluate policy decisions inside a one-off Docker container (isolated)."""

        def __init__(
            self,
            *,
            agent_id: AgentID,
            docker_client: DockerClient,
            engine: ApprovalPolicyEngine,
            image: str | None = None,
            timeout_secs: float | None = None,
        ) -> None:
            if not agent_id:
                raise ValueError("ContainerPolicyEvaluator requires agent_id")
            self.agent_id = agent_id
            self.image: str = image or resolve_runtime_image()
            self.timeout_secs = (
                timeout_secs if timeout_secs is not None else float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
            )
            self._docker = docker_client
            self._engine = engine
    ```

    **The correct approach:**

    Use `@dataclass` with `__post_init__` for defaulting logic:

    ```python
    from dataclasses import dataclass, field

    @dataclass
    class ContainerPolicyEvaluator:
        """Evaluate policy decisions inside a one-off Docker container (isolated)."""

        agent_id: AgentID
        docker_client: DockerClient
        engine: ApprovalPolicyEngine
        image: str | None = None
        timeout_secs: float | None = None

        # Private fields use field(init=False) or field(default=...)
        _docker: DockerClient = field(init=False, repr=False)
        _engine: ApprovalPolicyEngine = field(init=False, repr=False)

        def __post_init__(self) -> None:
            # Resolve defaults after init
            if self.image is None:
                self.image = resolve_runtime_image()
            if self.timeout_secs is None:
                self.timeout_secs = float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
            # Initialize private fields from public params
            self._docker = self.docker_client
            self._engine = self.engine
    ```

    Or even simpler - use `field(default_factory=...)`:

    ```python
    @dataclass
    class ContainerPolicyEvaluator:
        """Evaluate policy decisions inside a one-off Docker container (isolated)."""

        agent_id: AgentID
        docker_client: DockerClient
        engine: ApprovalPolicyEngine
        image: str = field(default_factory=resolve_runtime_image)
        timeout_secs: float = field(
            default_factory=lambda: float(os.getenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "5"))
        )
    ```

    **Problem 2: Redundant type check for agent_id**

    Line 34-35 checks `if not agent_id: raise ValueError`, but the type system
    already guarantees `agent_id: AgentID` is non-None. This is defensive programming
    that adds noise without value.

    **Current implementation (container.py, lines 34-35):**
    ```python
    if not agent_id:
        raise ValueError("ContainerPolicyEvaluator requires agent_id")
    ```

    **The correct approach:**

    Remove the check. If the type is `AgentID` (not `AgentID | None`), the type
    system guarantees it's present. Callers must provide it.

    If you're worried about empty string AgentIDs:
    ```python
    # Add validation to AgentID type itself, not at every usage site
    class AgentID(str):
        def __new__(cls, value: str):
            if not value:
                raise ValueError("AgentID cannot be empty")
            return super().__new__(cls, value)
    ```

    **Problem 3: Unnecessary payload variable**

    Line 52 creates a `payload` dict that's used only once in the next line. Should
    inline it in the function call.

    **Current implementation (container.py, lines 48-56):**
    ```python
    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        """Evaluate using the current policy source via run_policy_source."""
        payload = {"name": policy_input.name, "arguments": policy_input.arguments}
        policy_src, _ver = self._engine.get_policy()
        return run_policy_source(
            docker_client=self._docker,
            source=policy_src,
            input_payload=payload,
            image=self.image,
            timeout_secs=self.timeout_secs,
        )
    ```

    **The correct approach:**

    Inline the dict construction:
    ```python
    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        """Evaluate using the current policy source via run_policy_source."""
        policy_src, _ver = self._engine.get_policy()
        return run_policy_source(
            docker_client=self._docker,
            source=policy_src,
            input_payload={"name": policy_input.name, "arguments": policy_input.arguments},
            image=self.image,
            timeout_secs=self.timeout_secs,
        )
    ```

    **Problem 4: Manual dict construction instead of model_dump()**

    Line 52 manually constructs `{"name": ..., "arguments": ...}` from a Pydantic
    model. Should use `policy_input.model_dump()` or `policy_input.model_dump(include=...)`.

    **The correct approach:**

    Use Pydantic's serialization:
    ```python
    async def decide(self, policy_input: PolicyRequest) -> PolicyResponse:
        """Evaluate using the current policy source via run_policy_source."""
        policy_src, _ver = self._engine.get_policy()
        return run_policy_source(
            docker_client=self._docker,
            source=policy_src,
            input_payload=policy_input.model_dump(include={"name", "arguments"}),
            image=self.image,
            timeout_secs=self.timeout_secs,
        )
    ```

    Or if `PolicyRequest` only has `name` and `arguments` fields:
    ```python
    input_payload=policy_input.model_dump(),
    ```

    **Problem 5: Useless comment about moved code**

    Line 58 has a comment "## run_policy_source moved to adgn.agent.policy_eval.runner"
    documenting a past refactoring. This is noise - git history tracks moves.

    **Current implementation (container.py, line 58):**
    ```python
    ## run_policy_source moved to adgn.agent.policy_eval.runner
    ```

    **The correct approach:**

    Delete the comment entirely.

    **Benefits:**

    1. **Dataclass**: Less boilerplate, free __repr__, __eq__, type hints
    2. **No redundant checks**: Trust the type system, don't validate non-None at every usage
    3. **Concise code**: Inline single-use variables
    4. **Use platform primitives**: model_dump() instead of manual dict construction
    5. **Less noise**: No comments about past refactorings
  |||,
  properties=['use-dataclasses', 'trust-type-system', 'prefer-concise-code', 'use-platform-primitives', 'remove-noise'],
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [17, 46],  // Manual __init__ instead of @dataclass
      [34, 35],  // Redundant if not agent_id check
      [52, 52],  // Unnecessary payload variable and manual dict construction
      [58, 58],  // Useless comment about moved function
    ],
  },
  gap_note= |||
    This finding illustrates **"use-dataclasses"**: when a class is primarily a
    data container with simple field initialization, use `@dataclass` instead of
    writing manual `__init__` methods.

    When to use dataclasses:
    - Simple field initialization with no complex logic
    - Need __repr__, __eq__, __hash__ for free
    - Want type hints on fields visible to IDEs
    - Don't need fine control over initialization order

    When NOT to use dataclasses:
    - Complex validation logic in __init__
    - Need to compute fields from constructor arguments
    - Inheritance hierarchies with tricky initialization
    - Performance-critical code (minimal overhead but not zero)

    Dataclass benefits:
    - Less boilerplate (no manual field assignment)
    - Free __repr__ shows all fields
    - Free __eq__ compares by value
    - Type hints on fields (not just parameters)
    - Can use field(default_factory=...) for mutable defaults

    Related to **"trust-type-system"**: if a parameter is typed as `AgentID`
    (not `AgentID | None`), trust that callers provide it. Don't add runtime
    checks for what the type system already guarantees.

    When defensive checks ARE appropriate:
    - Validating user input from outside the system
    - Checking data from untyped sources (JSON, databases)
    - Enforcing business rules (not type correctness)
    - Validating invariants the type system can't express

    Related to **"use-platform-primitives"**: Pydantic models have `.model_dump()`
    for serialization. Don't manually construct dicts with `{"field": obj.field}`.

    Related to **"prefer-concise-code"**: inline variables used only once, don't
    create unnecessary intermediates.
  |||,
)
