local I = import '../../lib.libsonnet';

// iss-039: parse_response_messages should not exist, callers should type correctly

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale=|||
    parse_response_messages accepts Any and converts to list[ResponseOutputMessage]
    (openai_typing.py:111-123):

    def parse_response_messages(messages: Any) -> list[ResponseOutputMessage] | None:
        if not messages:
            return None
        return TypeAdapter(list[ResponseOutputMessage]).validate_python(messages)

    This function exists because callers hold untyped data and need runtime validation.

    Problem: This defers type safety to runtime. Callers should receive properly
    typed data from API responses directly.

    Should instead:
    1. Type API response parsing at source (where data enters system)
    2. Callers work with list[ResponseOutputMessage] | None from the start
    3. No runtime validation needed in application layer

    The function is a symptom of inadequate typing at API boundary.

    If using OpenAI SDK or similar, the response should already be typed.
    If parsing raw JSON, parse to typed Response object immediately, not dict[str, Any].

    Benefits of proper typing at source:
    - Type errors caught at compile time, not runtime
    - No defensive validation in application code
    - Clearer data flow: typed from API → typed throughout
    - No Any spreading through codebase

    Same principle applies to parse_chat_messages.
  |||,

  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [
      [111, 123],   // parse_response_messages function
      [136, 148],   // parse_chat_messages (same pattern)
    ],
  }
)
