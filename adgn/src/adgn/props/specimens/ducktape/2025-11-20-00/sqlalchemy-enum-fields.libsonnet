local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    SQLAlchemy models declare fields as Mapped[str] with inline comments indicating
    they should be enum types, but don't use the actual enum types.

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
  occurrences=[
    {
      files: { 'adgn/src/adgn/agent/persist/models.py': [61] },
      note: 'Run.status should use RunStatus enum',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: { 'adgn/src/adgn/agent/persist/models.py': [90] },
      note: 'Event.type should use EventType enum',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: { 'adgn/src/adgn/agent/persist/models.py': [152] },
      note: 'Policy.status should use PolicyStatus enum',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: { 'adgn/src/adgn/agent/persist/models.py': [178] },
      note: 'ChatMessage.author should use MessageAuthor enum',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      files: { 'adgn/src/adgn/agent/persist/models.py': [179] },
      note: 'ChatMessage.mime should use MessageMimeType enum',
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
  ],
)
