local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The shim.py module docstring (lines 14-17) says "Keep this tiny and dependency-free; only stdlib is used" but this is misleading. While the shim itself uses only stdlib, policy programs routinely import and use types/enums from the `adgn` package, which is installed in the container image.

    **Why this is misleading:**

    Policy programs typically use adgn package imports:
    ```python
    from adgn.agent.policies.policy_types import PolicyDecision
    from adgn.mcp._shared.naming import build_mcp_function
    return PolicyDecision.ALLOW
    ```

    **The confusion:**

    "Dependency-free" could mean:
    1. The shim.py module doesn't import non-stdlib (TRUE)
    2. Policy programs don't use adgn package (FALSE - they do!)
    3. No external packages needed in container (FALSE - adgn is needed)

    The current wording suggests interpretation #2, which is wrong.

    **Correct approach:**

    Clarify what "dependency-free" means:
    ```python
    Notes:
    - The shim itself only uses stdlib (no third-party imports).
    - Policy programs CAN import from adgn package (installed in container).
    - Container image must have the adgn package installed so both the shim
      (python -m adgn.agent.policy_eval.shim) and policy programs can use it.
    ```

    Or simply remove the misleading statement:
    ```python
    Notes:
    - Container image must have the adgn package installed for both the shim
      execution (python -m adgn.agent.policy_eval.shim) and for policy programs
      to import types/utilities from adgn.
    ```
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/shim.py': [[14, 17]],
  },
)
