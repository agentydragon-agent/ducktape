local I = import '../../specimens/lib.libsonnet';

// Consolidated issue: Variables assigned once and used immediately should be inlined

I.issueOneOccurrence(
  rationale= |||
    Multiple locations create intermediate variables that are assigned once and
    used immediately afterward. These variables add no semantic value and should
    be inlined at their use sites.

    Occurrences:

    1. local_runtime.py:123,144 - all_handlers variable
       Created from list(handlers) + self._extra_handlers, used once in
       MiniCodex.create call. Should inline the expression directly into the
       handlers parameter.

    2. mcp_routing.py:141-144 - body and response_headers variables
       Both created and used once in Response constructor. The transformations
       (b"".join() and dict comprehension) should be inlined directly into the
       Response() call.

    3. runtime.py:120-128, 188-196 - envelope and dumped variables
       Pattern appears twice: create Envelope, serialize with model_dump, pass
       to put_nowait/send_json. Should inline: Envelope(...).model_dump(mode="json")
       directly into the call, or extract to helper if pattern is common.

    4. reducer.py:60-61 - md variable
       Extracts evt.message.content, used once in AssistantMarkdownItem
       constructor. Should inline evt.message.content directly.

    5. sidecars.py:35-36, 58-59 - ui_server and loop_server variables
       Factory results used once in mount_inproc. Should inline make_ui_server()
       and make_loop_server() calls directly into mount_inproc arguments.

    6. handler.py:133-136 - result_model variable
       Result of convert_fastmcp_result used once in FunctionCallOutputPayload.
       Should inline the conversion call directly.

    Benefits of inlining:
    - Reduces line count and removes unnecessary names
    - Makes data flow clearer (transformation visible at use site)
    - Eliminates cognitive overhead of tracking intermediate variables
    - Standard pattern for single-use values

    Note: Variables that are used multiple times (e.g., base_system in
    local_runtime.py lines 142 and 152) should NOT be inlined to avoid
    duplication or re-evaluation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      123,          // all_handlers assignment
      144,          // all_handlers use in MiniCodex.create
    ],
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [141, 144],   // response_headers, body variables and return
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      [120, 128],   // send_json envelope and dumped
      [188, 196],   // _send_direct_all envelope and dumped
    ],
    'adgn/src/adgn/agent/server/reducer.py': [
      [60, 61],     // md variable and immediate use
    ],
    'adgn/src/adgn/agent/runtime/sidecars.py': [
      [35, 36],     // ui_server one-use variable
      [58, 59],     // loop_server one-use variable
    ],
    'adgn/src/adgn/agent/persist/handler.py': [
      [133, 136],   // result_model assignment and immediate use
    ],
  },
)
