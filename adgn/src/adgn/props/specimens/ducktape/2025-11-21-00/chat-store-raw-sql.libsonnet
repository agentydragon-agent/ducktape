local I = import '../lib.libsonnet';

// iss-012: ChatStorePersisted should use SQLAlchemy ORM instead of raw SQL

I.issue(
  snapshot='ducktape/2025-11-21-00',
  rationale=|||
    The `ChatStorePersisted` class in `adgn/src/adgn/mcp/chat/server.py` uses raw aiosqlite queries
    instead of SQLAlchemy ORM, making it inconsistent with the rest of the persistence layer.

    **Current state:**
    The ChatStorePersisted class (lines 171-283) uses raw aiosqlite queries via `self._persistence._open()` instead of SQLAlchemy ORM:
    - `last_id_async` (lines 182-189): raw SELECT MAX query
    - `get_last_read_async` (lines 191-200): raw SELECT with agent_id + server_name filter
    - `append` (lines 202-213): raw INSERT returning lastrowid
    - `get_message_async` (lines 215-229): raw SELECT by id with manual row conversion
    - `read_pending_and_advance` (lines 237-283): multiple raw queries with manual transaction handling

    **Why this is problematic:**

    1. **Inconsistent with codebase patterns**: The rest of the persistence layer uses SQLAlchemy ORM:
       ```python
       async with self._session() as session:
           result = await session.execute(select(Agent).where(Agent.id == agent_id))
           agent = result.scalar_one_or_none()
       ```

    2. **ORM models already exist**: `ChatMessage` and `ChatLastRead` models are defined in
       `adgn/src/adgn/agent/persist/models.py` (lines 197-225) but not being used.

    3. **Manual row parsing**: Uses `_row_to_message(row: Row)` converter (line 29) instead of
       automatic ORM object mapping.

    4. **Type safety**: Raw SQL with string-based queries is more error-prone than ORM with
       type-checked model attributes.

    5. **Maintenance**: SQL schema changes require manual updates to query strings and row
       parsers, while ORM models provide a single source of truth.

    6. **Raw database access**: Uses `_persistence._open()` (private method) instead of the
       proper `_session()` async context manager.

    **Recommended fix:**

    Refactor ChatStorePersisted to use SQLAlchemy ORM with `self._persistence._session()`:
    - Use `select(func.max(ChatMessage.id))` for `last_id_async`
    - Use `select(ChatLastRead.last_id)` with filters for `get_last_read_async`
    - Create ORM model instances for `append`, call `session.add()` and `commit()`
    - Use `select(ChatMessageModel)` for `get_message_async`, then convert ORM object to Pydantic ChatMessage

    **Benefits:**
    - Consistent with rest of codebase (follows established patterns)
    - Uses existing ORM models (single source of truth for schema)
    - Type-safe attribute access instead of string-based column names
    - Automatic schema migration support via Alembic
    - Easier to maintain and refactor
    - Better IDE support (autocomplete, type checking)
    - No manual row parsing needed

    **Note:**
    Line 5 imports `from aiosqlite import Row` and line 29 defines `_row_to_message(row: Row)`.
    These should be removed after migration to ORM, as they're only needed for raw SQL approach.
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
