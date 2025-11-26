local I = import '../../specimens/lib.libsonnet';

// iss-058: Delete install_policy_gateway wrapper function

I.issueOneOccurrence(
  rationale=|||
    Lines 279-298 define `install_policy_gateway()` which is just a wrapper around
    constructor + `add_middleware()`. This is unnecessary indirection.

    **Current:**
    ```python
    def install_policy_gateway(
        comp: Any,
        *,
        hub: ApprovalHub,
        policy_reader: PolicyReaderStub,
        pending_notifier: Callable[[str, str, str | None], Awaitable[None]] | None = None,
        record_outcome: Callable[[str, str, ApprovalOutcome], Awaitable[None]] | None = None,
    ) -> PolicyGatewayMiddleware:
        """Install PolicyGatewayMiddleware on a FastMCP-like server."""
        middleware = PolicyGatewayMiddleware(
            hub=hub, pending_notifier=pending_notifier, record_outcome=record_outcome, policy_reader=policy_reader
        )
        comp.add_middleware(middleware)
        return middleware
    ```

    **Problem:** This is a fancy, confusing wrapper around:
    1. Create middleware instance
    2. Call `comp.add_middleware()`
    3. Return the instance

    Callers can do this themselves in 2 lines. The function adds no value.

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
