local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Middleware explicitly catches KeyError and ValueError, converting to 500 responses
    (mcp_routing.py:146-148):

    except (KeyError, ValueError) as e:
        logger.error(f"Routing error: {e}")
        return Response(content=str(e), status_code=500)

    Problems:
    - Catches exceptions that indicate bugs, not expected errors
    - Masks real issues by returning 500 instead of propagating
    - No stack trace in response (only logged)
    - Inconsistent: other exceptions propagate up

    Should either:
    1. Remove try/except, let framework handle unhandled exceptions
    2. Install global error handling middleware if custom 500 responses needed
    3. Only catch specific expected exceptions with proper error responses

    KeyError accessing token_info["role"] means invalid TOKEN_TABLE data (bug).
    ValueError converting TokenRole means invalid data in table (bug).

    These should fail fast, not return generic 500. Framework should handle
    unexpected exceptions consistently across all endpoints.

    If custom error responses needed, use Starlette exception handlers or
    middleware, not scattered try/except blocks.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [146, 148],   // except (KeyError, ValueError) catch
    ],
  },
)
