local I = import '../../specimens/lib.libsonnet';

// iss-011: ChatMessage author and mime should use StrEnum types

I.issueOneOccurrence(
  rationale=|||
    ChatMessage model uses Mapped[str] for author and mime fields (models.py:178-179),
    but these likely have fixed valid values.

    author: Mapped[str] - Probably "user" vs "assistant" or similar
    mime: Mapped[str] - Probably "text/plain" vs "text/markdown"

    If these fields have a fixed set of valid values (not arbitrary strings),
    they should use StrEnum types for type safety and validation.

    Should investigate actual usage to determine:
    1. What values does author take? (user/assistant/system?)
    2. What values does mime take? (text/plain, text/markdown, text/html?)

    If fixed set: create MessageAuthor and MessageMimeType enums, use typed fields.
    If truly arbitrary: keep as str but add validation logic explaining why.

    Benefits of enums (if applicable):
    - Type safety and autocomplete
    - Runtime validation
    - Clear documentation of valid values
    - Refactoring support
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      178,          // author: Mapped[str]
      179,          // mime: Mapped[str]
    ],
  }
)
