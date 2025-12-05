local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 171-283 define `ChatStorePersisted` using raw aiosqlite queries via `_persistence._open()`
    instead of SQLAlchemy ORM, inconsistent with the rest of the persistence layer.

    Five methods use raw SQL: `last_id_async` (SELECT MAX), `get_last_read_async` (SELECT with
    filters), `append` (INSERT returning lastrowid), `get_message_async` (SELECT by id),
    `read_pending_and_advance` (multiple queries with manual transaction handling).

    Problems: inconsistent with codebase patterns (rest of persistence uses SQLAlchemy ORM with
    `_session()` context manager); ORM models (`ChatMessage`, `ChatLastRead`) already exist in
    persist/models.py but aren't used; manual row parsing via `_row_to_message(row: Row)`
    (line 29) instead of automatic ORM mapping; raw SQL with string-based queries is error-prone
    (no type checking); schema changes require manual updates to query strings and row parsers;
    uses private `_open()` method instead of proper `_session()` context manager.

    Line 5 imports aiosqlite.Row only for raw SQL approach. Lines 29-37 define the manual
    converter.

    Refactor to use SQLAlchemy ORM: `select(func.max(...))`, `select(...).where(...)`, ORM model
    instances with `session.add()`/`commit()`. Benefits: consistency, uses existing models (single
    source of truth), type-safe attribute access, Alembic migration support, better IDE support.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/chat/server.py': [
      [5, 5],       // Import aiosqlite.Row (should use ORM models instead)
      [29, 37],     // _row_to_message converter (not needed with ORM)
      [171, 283],   // ChatStorePersisted class using raw SQL
      [182, 189],   // last_id_async - raw SELECT MAX query
      [191, 200],   // get_last_read_async - raw SELECT query
      [202, 213],   // append - raw INSERT query
      [215, 229],   // get_message_async - raw SELECT query
      [237, 283],   // read_pending_and_advance - multiple raw SQL queries
    ],
  },
)
