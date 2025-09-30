local I = import '../../specimens/lib.libsonnet';

// iss-026: Walrus operator — bind and check gitstatusd response in one line
I.issueWithOccurrences(
  rationale=|||
    Use walrus to bind and check the parsed response in a single, readable line.

    Before:

        response_data = raw_response.rstrip("\x1e")
        if not response_data:
            raise GitStatusdParseError("Empty response from gitstatusd")

    After:

        if not (response_data := raw_response.rstrip("\x1e")):
            raise GitStatusdParseError("Empty response from gitstatusd")
  |||,
  // properties=['walrus'],
  occurrences=[{ files: { 'wt/wt/server/gitstatusd_client.py': [[188, 188]] }, note: 'Replace two-line parse with walrus form.' }],
)
