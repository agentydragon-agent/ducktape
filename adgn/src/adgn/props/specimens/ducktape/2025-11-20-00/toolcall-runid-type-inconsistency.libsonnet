local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The persistence API models run identifiers inconsistently: RunRow.id is typed as UUID,
    but ToolCallRecord.run_id is typed as str | None. This forces callers to manually convert
    UUIDs to strings when working with tool call records, and forgetting the conversion causes
    runtime errors when SQLite cannot bind a UUID object to a String column.

    The fix should make UUID binding transparent at the ORM level by using SQLAlchemy's Uuid
    column type instead of String in the models (persist/models.py). Change Run.id from
    Mapped[str] to Mapped[UUID], and ToolCall.run_id from Mapped[str | None] to
    Mapped[UUID | None]. Update ToolCallRecord.run_id in the Pydantic API to UUID | None.
    This lets SQLAlchemy handle string serialization for SQLite transparently while keeping
    UUID as the canonical Python type throughout, eliminating manual str(run_id) conversions.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/__init__.py': [[70, 70], [115, 115]],
    'adgn/src/adgn/agent/persist/models.py': [[57, 57], [115, 115]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/persist/__init__.py', 'adgn/src/adgn/agent/persist/models.py'],
  ],
)
