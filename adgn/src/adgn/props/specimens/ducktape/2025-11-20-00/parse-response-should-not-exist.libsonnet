local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    parse_response_messages accepts Any and converts to list[ResponseOutputMessage].
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
  occurrences=[
    {
      files: {
        'adgn/src/adgn/llm/sysrw/openai_typing.py': [[111, 123]],
      },
      note: 'parse_response_messages function',
      expect_caught_from: [['adgn/src/adgn/llm/sysrw/openai_typing.py']],
    },
    {
      files: {
        'adgn/src/adgn/llm/sysrw/openai_typing.py': [[136, 148]],
      },
      note: 'parse_chat_messages function',
      expect_caught_from: [['adgn/src/adgn/llm/sysrw/openai_typing.py']],
    },
  ],
)
