local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Function read_text_json is a special case of read_text_json_typed with output_type=dict[str, Any].
    Having both functions creates maintenance burden and API surface bloat.
    Either replace callers to use read_text_json_typed(session, uri, dict[str, Any]) directly, or delegate read_text_json to call read_text_json_typed internally.
    The preferred approach is to replace callers, as it makes the type contract explicit at each call site.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/_shared/resources.py': [[32, 41]]},
)
