local I = import '../../specimens/lib.libsonnet';

// iss-033: Should inline body and response_headers into Response

I.issueOneOccurrence(
  rationale=|||
    Code creates intermediate variables for body and response_headers, used once
    immediately (mcp_routing.py:141-144):

    # Return the response
    response_headers = {k.decode(): v.decode() for k, v in headers}
    body = b"".join(body_parts)
    return Response(content=body, status_code=status_code, headers=response_headers)

    Should inline both:
    return Response(
        content=b"".join(body_parts),
        status_code=status_code,
        headers={k.decode(): v.decode() for k, v in headers}
    )

    Benefits:
    - Less code: removes two variables
    - Clearer: transformations visible at use site
    - No naming overhead for single-use values
    - Comment "Return the response" is redundant with return statement

    The variables don't add clarity, just line count.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers', 'no-useless-comments'],
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [141, 144],   // response_headers, body variables and return
    ],
  },
)
