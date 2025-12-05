local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Both TokenAuthMiddleware and UITokenAuthMiddleware duplicate the same
    Bearer token extraction logic:

    TokenAuthMiddleware.dispatch() (lines 75-91):
    - Check if Authorization header exists
    - Split on whitespace
    - Validate format is "Bearer <token>"
    - Extract the token (parts[1])

    UITokenAuthMiddleware.__call__() (lines 144-161):
    - Same exact pattern with slightly different error handling

    This is classic code duplication. Both implementations:
    1. Check if Authorization header exists
    2. Split on whitespace
    3. Validate format is "Bearer <token>"
    4. Extract the token (parts[1])

    Fix options:
    1. Extract a shared helper function: extract_bearer_token(auth_header)
       that returns (token | None, error_dict | None)

    2. Preferred: Use FastMCP's authentication patterns if available
       (investigate if FastMCP provides built-in Bearer token middleware,
       authentication dependency injection, or standard auth utilities)

    3. Consolidate middleware: if both are doing the same thing (Bearer
       token validation), consider a single parameterized middleware:
       BearerTokenMiddleware(token_validator: Callable)

    Most modern Python web frameworks (FastAPI, Starlette, etc.) provide
    standardized auth patterns. If FastMCP builds on these, use the provided
    patterns instead of rolling custom middleware.

    This eliminates the duplication entirely by extracting or unifying the
    two use cases.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [75, 91],   // TokenAuthMiddleware extracts Bearer token
      [144, 161], // UITokenAuthMiddleware extracts Bearer token
    ],
  },
)
