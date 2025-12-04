local I = import '../../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    Class uses manual `__init__` for simple field initialization when `@dataclass`
    would be more concise and provide additional benefits.

    **Current code (container.py:17-46):**
    ```python
    class ContainerPolicyEvaluator:
        def __init__(
            self,
            agent_id: AgentID,
            persistence: Optional[Persistence],
            runtime_image: str,
            ...
        ):
            self.agent_id = agent_id
            self.persistence = persistence
            self.runtime_image = runtime_image
            ...
    ```

    Simple assignment-only initialization is a perfect candidate for `@dataclass`.

    **Correct approach:**
    ```python
    from dataclasses import dataclass

    @dataclass
    class ContainerPolicyEvaluator:
        agent_id: AgentID
        persistence: Optional[Persistence]
        runtime_image: str
        ...

        # Use __post_init__ if needed for complex initialization
    ```

    **Benefits:**
    - Less boilerplate (no manual assignments)
    - Free `__repr__` for debugging
    - Free `__eq__` for testing
    - Type annotations serve as field declarations
    - Standard Python idiom for data-holding classes
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [17, 46],  // Manual __init__ instead of @dataclass
    ],
  },
)
