local I = import '../lib.libsonnet';

// SQLAlchemy models use Mapped[str] with enum comments instead of actual enum types

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale= |||
    SQLAlchemy models declare fields as Mapped[str] with inline comments indicating
    they should be enum types, but don't use the actual enum types.

    Affected fields:
    - Policy.status (line 152): comment says "active|proposed|rejected|superseded (PolicyStatus)"
    - Run.status (line 61): comment says "RunStatus enum value"
    - Event.type (line 90): comment says "EventType enum value"
    - ChatMessage.author (line 178): likely "user" vs "assistant" or similar
    - ChatMessage.mime (line 179): likely "text/plain" vs "text/markdown"

    All corresponding enums exist as StrEnum types:
    - PolicyStatus (defined in models.py)
    - RunStatus (server/protocol.py:80)
    - EventType (persist/__init__.py:54)

    SQLAlchemy 2.0+ supports native Python Enum mapping. Should use:
    status: Mapped[PolicyStatus] = mapped_column(nullable=False)

    Benefits:
    - Type safety: can't assign arbitrary strings
    - IDE autocomplete for valid values
    - Runtime validation (can't save invalid values)
    - No need for inline comments listing valid values
    - Consistency with enum definitions
    - Refactoring support

    SQLAlchemy automatically maps Python enums to VARCHAR/String columns while
    preserving enum type semantics in Python code.

    For ChatMessage fields (author/mime), if they have fixed sets of valid values,
    create MessageAuthor and MessageMimeType enums. If truly arbitrary strings,
    keep as str but add validation logic explaining why.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      61,           // Run.status: Mapped[str] with RunStatus comment
      90,           // Event.type: Mapped[str] with EventType comment
      152,          // Policy.status: Mapped[str] with PolicyStatus comment
      178,          // ChatMessage.author: Mapped[str]
      179,          // ChatMessage.mime: Mapped[str]
    ],
  },
)
