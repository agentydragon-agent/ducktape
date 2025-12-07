local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    chat_param_message_content_as_text (lines 75-105) claims to "extract text content", but when
    content is not a plain string (e.g., multi-part ChatCompletion*MessageParam with structured
    content like [{'type': 'text', 'text': 'hi'}]), it falls back to str(content) (lines 85, 92,
    99, 104), returning the Python repr of the structure instead of the actual text. This is
    misleading and makes it easy to abuse the API - callers receive strings like "[{'type':
    'text', 'text': 'hi'}]" and may not realize they're getting repr output rather than extracted
    text. The function should be designed to make abuse hard: it should expect text-only content
    and either raise an exception or return None (with a return type like str | None) when called
    on non-text content, forcing callers to handle structured content explicitly. The name and
    docstring should also clarify that this is only for text-only messages.
  |||,
  filesToRanges={
    'adgn/src/adgn/llm/sysrw/openai_typing.py': [[85, 85], [92, 92], [99, 99], [104, 104]],
  },
)
