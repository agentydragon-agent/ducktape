local I = import '../../specimens/lib.libsonnet';

// iss-008: Inline result_model variable in on_tool_result_event

I.issueOneOccurrence(
  rationale=|||
    Method on_tool_result_event uses intermediate variable result_model that's assigned once and used
    immediately in next line.

    Current pattern (lines 133-136):
    result_model = convert_fastmcp_result(evt.result)
    self._record_event(
        type=EventType.FUNCTION_CALL_OUTPUT,
        payload=FunctionCallOutputPayload(call_id=evt.call_id, result=result_model),
        ...
    )

    Should inline:
    self._record_event(
        type=EventType.FUNCTION_CALL_OUTPUT,
        payload=FunctionCallOutputPayload(
            call_id=evt.call_id,
            result=convert_fastmcp_result(evt.result)
        ),
        ...
    )

    The variable has no semantic value - it's not reused, not checked, not logged.
    It only adds line count and an extra name to track.

    Inlining improves readability by showing the transformation inline at the use site.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/handler.py': [
      [133, 136],   // result_model assignment and immediate use
    ],
  },
)
