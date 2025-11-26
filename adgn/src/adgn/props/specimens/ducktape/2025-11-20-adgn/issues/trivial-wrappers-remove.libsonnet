local I = import '../../specimens/lib.libsonnet';

// iss-040: Trivial wrapper functions should not exist

I.issueOneOccurrence(
  rationale=|||
    Several functions are one-line trivial wrappers around Pydantic methods.

    dump_response_messages (openai_typing.py:126-128):
    def dump_response_messages(messages: list[ResponseOutputMessage]) -> list[dict[str, Any]]:
        return [msg.model_dump(by_alias=True) for msg in messages]

    dump_chat_messages (openai_typing.py:131-133):
    def dump_chat_messages(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
        return [TypeAdapter(dict[str, Any]).validate_python(msg) for msg in messages]

    parse_tool_params (openai_typing.py:159-169):
    def parse_tool_params(params: dict[str, Any]) -> dict[str, Any]:
        return TypeAdapter(dict[str, Any]).validate_python(params)

    Problems:
    - No abstraction value: just call the underlying method directly
    - Extra function call overhead
    - More code to maintain
    - Adds name to API without adding functionality
    - Makes codebase harder to navigate (extra indirection)

    Callers should just use:
    - [msg.model_dump(by_alias=True) for msg in messages]
    - TypeAdapter(dict[str, Any]).validate_python(msg)
    - TypeAdapter(dict[str, Any]).validate_python(params)

    Only create wrapper functions when they:
    1. Add real abstraction (combine multiple operations)
    2. Provide domain-specific naming (clarify intent)
    3. Encapsulate complex logic

    These wrappers do none of those things.
  |||,

  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [
      [126, 128],   // dump_response_messages
      [131, 133],   // dump_chat_messages
      [159, 169],   // parse_tool_params
    ],
  },
)
