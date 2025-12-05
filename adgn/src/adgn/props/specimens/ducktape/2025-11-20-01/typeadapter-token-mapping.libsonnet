local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 44-56 manually parse JSON and validate dict[str, str] structure with explicit
    isinstance checks and an imperative loop. This should use Pydantic's TypeAdapter
    for cleaner code and better error messages.

    Current approach: json.loads + manual dict check + loop with isinstance checks for
    each key/value pair. Problems: verbose (10 lines vs 3), generic error messages
    don't specify which field failed, duplicates validation logic Pydantic provides.

    Replace with TypeAdapter: 3 lines using adapter.validate_json() + dict comprehension
    to convert to AgentID. Benefits: integrated JSON parsing and validation, detailed
    validation errors with locations, no manual isinstance checks, more Pythonic.

    AgentID is NewType("AgentID", str), so dict comprehension conversion is safe.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [44, 55],  // Manual JSON parsing and validation loop
      [10, 10],  // import json - may be removable
    ],
  },
)
