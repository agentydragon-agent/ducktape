local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Variables assigned once and used immediately afterward add no semantic value
    and should be inlined at their use sites.

    Benefits of inlining:
    - Reduces line count and removes unnecessary names
    - Makes data flow clearer (transformation visible at use site)
    - Eliminates cognitive overhead of tracking intermediate variables
    - Standard pattern for single-use values

    Note: Variables used multiple times should NOT be inlined to avoid
    duplication or re-evaluation.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/runtime/local_runtime.py': [123, 144],
      },
      note: 'all_handlers variable created from list(handlers) + self._extra_handlers, used once in MiniCodex.create call',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/local_runtime.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/mcp_routing.py': [[141, 144]],
      },
      note: 'body and response_headers variables both created and used once in Response constructor',
      expect_caught_from: [['adgn/src/adgn/agent/server/mcp_routing.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/runtime.py': [[120, 128], [188, 196]],
      },
      note: 'envelope and dumped variables: create Envelope, serialize with model_dump, pass to put_nowait/send_json',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/reducer.py': [[60, 61]],
      },
      note: 'md variable extracts evt.message.content, used once in AssistantMarkdownItem constructor',
      expect_caught_from: [['adgn/src/adgn/agent/server/reducer.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/runtime/sidecars.py': [[35, 36], [58, 59]],
      },
      note: 'ui_server and loop_server variables: factory results used once in mount_inproc',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/sidecars.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/persist/handler.py': [[133, 136]],
      },
      note: 'result_model variable: result of convert_fastmcp_result used once in FunctionCallOutputPayload',
      expect_caught_from: [['adgn/src/adgn/agent/persist/handler.py']],
    },
  ],
)
