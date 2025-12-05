local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `abort_run` function (lines 672-689) is a trivial alias that wraps `abort_agent` (lines 642-651), adding only a `SimpleOk` return value. It should be deleted. The 15-line docstring makes the function appear more substantial than the 2-line implementation.

    **Why this is problematic:**

    1. **Unnecessary alias**: The function just calls `abort_agent` and wraps the result in `SimpleOk`.
       This provides no value - callers should just call `abort_agent` directly.

    2. **Confusing API**: Having two functions that do the same thing creates confusion about which
       one to use. Is there a semantic difference? (No, the docstring admits it's just an alias.)

    3. **Return type inconsistency**: `abort_agent` returns `None`, `abort_run` returns `SimpleOk`.
       This is described as "for consistency" but it's actually inconsistent - now there are two
       different return types for the same operation.

    4. **Verbose docstring for trivial code**: The 15-line docstring describes a 2-line function.
       The docstring has:
       - Summary line
       - Detailed explanation
       - Args section
       - Returns section
       - Raises section

       For a function that literally just calls another function and wraps the result.

    5. **Misleading docstring**: Says "This is a semantic alias for abort_agent that returns SimpleOk
       for consistency." What consistency? If it's just an alias, why does it exist?

    6. **YAGNI violation**: There's no evidence that this alias is needed. If some callers prefer
       `SimpleOk` return type, they can wrap it themselves.

    **Recommended fix:**

    Delete lines 672-689 entirely. Callers should use `abort_agent` directly and wrap in `SimpleOk` at the call site if needed.

    **Benefits:**
    - Simpler API with one clear way to abort
    - No confusion about which function to use
    - Less code to maintain
    - No verbose docstring for trivial wrapper
    - Consistent return types (abort operations return None)

    **Note:**
    If this alias exists because some callers specifically need `SimpleOk`, that's a code smell.
    The caller should handle the wrapping, not create a duplicate function in the API.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [672, 689],  // abort_run alias with verbose docstring
      [642, 651],  // abort_agent original function (for comparison)
    ],
  },
)
