local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Code strips "Bearer " prefix using magic number slice (mcp_routing.py:72-73):

    if auth_value.startswith("Bearer "):
        return auth_value[7:]  # Strip "Bearer " prefix

    Problems:
    - Magic number 7: not self-documenting
    - Fragile: if prefix changes, must update both check and slice
    - Duplicates prefix string literal

    Should use removeprefix (Python 3.9+):
    BEARER_PREFIX = "Bearer "
    if auth_value.startswith(BEARER_PREFIX):
        return auth_value.removeprefix(BEARER_PREFIX)

    Or simpler:
    if auth_value.startswith(BEARER_PREFIX):
        return auth_value[len(BEARER_PREFIX):]

    Best: just use removeprefix unconditionally if you know it's there:
    BEARER_PREFIX = "Bearer "
    # After checking startswith:
    return auth_value.removeprefix(BEARER_PREFIX)

    Benefits:
    - Self-documenting: removeprefix clearly shows intent
    - DRY: prefix defined once as constant
    - Safer: removeprefix is no-op if prefix not present
    - Standard Python idiom

    Constant should be module-level for reuse across auth code.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [72, 73],     // Bearer prefix check and magic [7:] slice
    ],
  },
)
