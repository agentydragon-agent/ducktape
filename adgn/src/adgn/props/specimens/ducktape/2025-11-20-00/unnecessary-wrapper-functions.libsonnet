local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Trivial wrapper functions that add no abstraction value. Only create wrapper
    functions when they add real abstraction (combine multiple operations),
    provide domain-specific naming clarity, or encapsulate complex logic.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/llm/sysrw/openai_typing.py': [[126, 128], [131, 133], [159, 169]],
      },
      note: 'dump_response_messages/dump_chat_messages/parse_tool_params are one-line wrappers around Pydantic methods',
      expect_caught_from: [['adgn/src/adgn/llm/sysrw/openai_typing.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/agent.py': [[149, 160], 269],
      },
      note: '_normalize_call_arguments accepts dict[str, Any] | str | None but dict case never occurs; defensive check for impossible case',
      expect_caught_from: [['adgn/src/adgn/agent/agent.py']],
    },
  ],
)
