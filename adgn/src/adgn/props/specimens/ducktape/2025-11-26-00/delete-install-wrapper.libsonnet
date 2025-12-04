local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 279-298 define `install_policy_gateway()` which is just a wrapper around
    constructor + `add_middleware()`. This is unnecessary indirection.

    **Current pattern:**
    `install_policy_gateway(comp, hub=..., policy_reader=..., ...)` creates a
    `PolicyGatewayMiddleware` instance, calls `comp.add_middleware(middleware)`, and
    returns the middleware.

    **Problem:** This is just a wrapper around `middleware = PolicyGatewayMiddleware(...);
    comp.add_middleware(middleware)`. Callers can do this themselves in 2 lines.

    **Fix:** Delete the function. Callers should do:
    ```python
    middleware = PolicyGatewayMiddleware(hub=hub, policy_reader=policy_reader, ...)
    comp.add_middleware(middleware)
    ```

    **Benefits:**
    1. Fewer functions to maintain
    2. Clearer what's happening - no magic wrapper
    3. Standard pattern (create middleware, add it)
    4. No confusing mutable-state wrapper around compositor

    **Docstring claim:** "This mirrors production wiring in the container; tests should
    reuse this helper to avoid drift." This is not a good reason - tests should just
    use the same 2-line pattern as production. The "drift" risk is minimal and the
    indirection cost is higher.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [279, 298],  // Unnecessary wrapper function
    ],
  },
)
