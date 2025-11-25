local I = import '../../specimens/lib.libsonnet';

// iss-029: ContainerPolicyEvaluator should be dataclass and remove redundant checks

I.issueOneOccurrence(
  rationale= |||
    The `ContainerPolicyEvaluator` class has multiple issues:

    **Problem 1: Manual class instead of dataclass**

    The class has simple field initialization with no special logic, making it a
    perfect candidate for `@dataclass`. Using a manual `__init__` is verbose and
    adds no value.

    **The correct approach:**

    Use `@dataclass` with `field(default_factory=...)` for dynamic defaults, or
    `__post_init__` for more complex initialization. Gets free `__repr__`, `__eq__`,
    and reduces boilerplate.

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

    **Problem 3: Unnecessary payload variable + manual dict construction**

    Line 52 creates a `payload` dict that's used only once, and manually constructs
    it from a Pydantic model instead of using `model_dump()`.

    **The correct approach:**

    Inline and use `policy_input.model_dump(include={"name", "arguments"})` to
    serialize the Pydantic model properly.

    **Problem 4: Useless comment about moved code**

    Line 58 has a comment "## run_policy_source moved to adgn.agent.policy_eval.runner"
    documenting a past refactoring. This is noise - git history tracks moves.

    **Current implementation (container.py, line 58):**
    ```python
    ## run_policy_source moved to adgn.agent.policy_eval.runner
    ```

    **The correct approach:**

    Delete the comment entirely.

    **Summary:**

    1. Use `@dataclass` for simple initialization (lines 17-46)
    2. Remove redundant `if not agent_id` check (lines 34-35)
    3. Inline payload and use `model_dump(include=...)` (line 52)
    4. Delete comment about moved function (line 58)
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
