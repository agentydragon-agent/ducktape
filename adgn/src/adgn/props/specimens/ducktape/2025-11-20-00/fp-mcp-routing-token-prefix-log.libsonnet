local I = import '../../lib.libsonnet';

I.falsePositive(
  rationale= |||
    Critics flagged the invalid-token logging (line 110: `logger.warning(f"Invalid token:
    {token[:10]}...")`) as a credential leak - logging partial tokens would be problematic in
    production systems. However, this is acceptable in this context because: (a) this is a personal
    pet project, not production infrastructure, so the security bar is lower and log storage isn't
    treated as a security liability, (b) the bearer tokens used are long (cryptographically
    random), so 10 characters isn't enough information to be exploitable, and (c) the tokens are
    stored in plaintext JSON files anyway (auth.py:24-36 loads from --auth-tokens file). Anyone
    with filesystem access to read logs can already read the full tokens from the configuration
    file, making the log prefix leak moot. While it would be marginally better to log fewer
    characters (e.g., 5), or use a hash, the current practice isn't worth fixing for this use case.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [[110, 110]],
  },
)
