local I = import '../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale= |||
    Multiple trivial wrapper functions that add no abstraction value.

    1. dump_response_messages/dump_chat_messages/parse_tool_params (openai_typing.py:126-169)
    are one-line wrappers around Pydantic methods. Callers should invoke model_dump(by_alias=True)
    or TypeAdapter directly instead of going through an extra function call.

    2. _normalize_call_arguments (agent.py:149-160) accepts dict[str, Any] | str | None but the
    dict case never occurs. The only caller passes FunctionCallItem.arguments typed as str | None.
    All construction paths guarantee JSON string format. The runtime type check and fallback
    json.dumps() are defensive programming against a case that cannot happen according to the
    type system.

    Only create wrapper functions when they add real abstraction (combine multiple operations),
    provide domain-specific naming clarity, or encapsulate complex logic. These do none of those.
  |||,
  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [
      [126, 128],
      [131, 133],
      [159, 169],
    ],
    'adgn/src/adgn/agent/agent.py': [
      [149, 160],
      269,
    ],
  },
)
