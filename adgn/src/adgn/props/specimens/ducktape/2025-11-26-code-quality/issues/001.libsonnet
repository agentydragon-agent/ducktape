local I = import '../../specimens/lib.libsonnet';

// iss-001: _policy_gateway uses Any type instead of PolicyGatewayMiddleware

I.issueOneOccurrence(
  rationale= |||
    The `_policy_gateway` field in AgentRuntimeContainer is typed as `Any | None` with a
    comment indicating it should be `PolicyGatewayMiddleware`, but the proper type is not
    used.

    **Current implementation (container.py:197):**
    ```python
    _policy_gateway: Any | None = field(default=None, init=False)  # PolicyGatewayMiddleware
    ```

    **Problems:**
    1. **Loss of type safety**: `Any` defeats the purpose of type checking
    2. **Misleading comment**: If we know the type, we should use it
    3. **IDE limitations**: No autocomplete or type hints when using this field
    4. **Maintenance burden**: Comment can drift from reality

    **Correct approach:**
    ```python
    from adgn.mcp.policy_gateway.middleware import PolicyGatewayMiddleware

    _policy_gateway: PolicyGatewayMiddleware | None = field(default=None, init=False)
    ```

    **Benefits:**
    1. Proper type checking catches errors at development time
    2. IDE autocomplete and navigation work correctly
    3. Self-documenting - no need for comment
    4. Safer refactoring - type checker catches breaking changes
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/container.py': [
      [197, 197],  // _policy_gateway: Any | None field declaration
    ],
  },
)
