local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Line 197 in container.py types `_policy_gateway` as `Any | None` with a comment
    indicating it should be `PolicyGatewayMiddleware`, but doesn't use the proper type.

    **Problems:**
    1. Loss of type safety - `Any` defeats type checking
    2. Misleading comment - if we know the type, use it in the annotation
    3. IDE limitations - no autocomplete or type hints when using this field
    4. Maintenance burden - comment can drift from reality

    **Fix:** Import `PolicyGatewayMiddleware` from `adgn.mcp.policy_gateway.middleware`
    and change the type annotation to `PolicyGatewayMiddleware | None`. Remove the comment.

    This enables proper type checking, IDE support, and makes the code self-documenting.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/container.py': [
      [197, 197],  // _policy_gateway: Any | None field declaration
    ],
  },
)
