local I = import '../../specimens/lib.libsonnet';

// iss-032: Should walrus token_info and remove useless comment

I.issueOneOccurrence(
  rationale=|||
    Code looks up token_info, checks if None, with useless comment (mcp_routing.py:107-111):

    # Look up token
    token_info = self.token_table.get(token)
    if not token_info:
        logger.warning(f"Invalid token: {token[:10]}...")
        return Response(content="Invalid token", status_code=401)

    Problems:
    - Comment "Look up token" adds no information beyond code itself
    - Assign-then-check pattern should use walrus

    Should be:
    if not (token_info := self.token_table.get(token)):
        logger.warning(f"Invalid token: {token[:10]}...")
        return Response(content="Invalid token", status_code=401)

    Benefits:
    - No useless comment
    - More concise with walrus operator
    - Standard pattern for dict.get() + None check

    The comment is purely descriptive of what the code obviously does.
  |||,
  properties=['no-useless-comments', 'python/walrus-operator'],
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [107, 111],   // "Look up token" comment and assign-check pattern
    ],
  },
)
