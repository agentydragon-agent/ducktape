local I = import '../../specimens/lib.libsonnet';

// iss-028: SQLAlchemy and database quality issues

I.issueOneOccurrence(
  rationale= |||
    Multiple issues in the SQLAlchemy persistence layer:

    **Problem 1: Inline comments instead of proper SQLAlchemy comments**

    ORM field definitions use inline Python comments (`# MCPConfig as JSON`) instead
    of SQLAlchemy's `comment=` parameter, which would make these descriptions visible
    in the database schema and help DBAs/database tools.

    **Current implementation (models.py, lines 68-69, 92, 122, 125-126, etc.):**
    ```python
    mcp_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # MCPConfig as JSON
    preset: Mapped[str] = mapped_column(String, nullable=False)  # Agent preset name
    id: Mapped[UUID] = mapped_column(String, primary_key=True)  # UUID stored as string
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # Sequence number within run
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # Typed payload per EventType
    call_id: Mapped[str | None] = mapped_column(String, nullable=True)  # For tool call correlation
    ```

    **The correct approach:**

    Use SQLAlchemy's `comment=` parameter:
    ```python
    mcp_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="MCPConfig as JSON"
    )
    preset: Mapped[str] = mapped_column(
        String, nullable=False, comment="Agent preset name"
    )
    id: Mapped[UUID] = mapped_column(
        String, primary_key=True, comment="UUID stored as string"
    )
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Sequence number within run"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="Typed payload per EventType"
    )
    call_id: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="For tool call correlation"
    )
    ```

    **Benefits:**
    - Comments visible in `PRAGMA table_info` (SQLite) or `\d` (PostgreSQL)
    - Database tools/IDEs show column descriptions
    - DBAs can understand schema without reading Python code
    - Migrations preserve documentation

    **Problem 2: Raw SQL instead of ORM for last_activity query**

    The `list_agents_last_activity()` method uses raw SQL with `text()` instead of
    SQLAlchemy ORM constructs, making it harder to maintain and less portable.

    **Current implementation (sqlite.py, lines 145-165):**
    ```python
    async def list_agents_last_activity(self) -> dict[AgentID, datetime | None]:
        async with self._session() as session:
            # This is complex to do purely in ORM, so we'll use raw SQL
            result = await session.execute(
                text("""
    SELECT a.id as agent_id,
           MAX(
             COALESCE(e.event_at, r.finished_at, r.started_at, a.created_at)
           ) as last_ts
    FROM agents a
    LEFT JOIN runs r ON r.agent_id = a.id
    LEFT JOIN events e ON e.run_id = r.id
    GROUP BY a.id
                    """)
            )
            return {AgentID(row.agent_id): row.last_ts for row in result}
    ```

    **The correct approach:**

    Use SQLAlchemy ORM with `func.max()` and `func.coalesce()`:
    ```python
    async def list_agents_last_activity(self) -> dict[AgentID, datetime | None]:
        async with self._session() as session:
            # Use ORM constructs for type safety and portability
            last_activity = func.max(
                func.coalesce(
                    Event.event_at,
                    Run.finished_at,
                    Run.started_at,
                    Agent.created_at
                )
            ).label("last_ts")

            result = await session.execute(
                select(Agent.id.label("agent_id"), last_activity)
                .outerjoin(Run, Run.agent_id == Agent.id)
                .outerjoin(Event, Event.run_id == Run.id)
                .group_by(Agent.id)
            )
            return {AgentID(row.agent_id): row.last_ts for row in result}
    ```

    **Benefits:**
    - Type-safe: SQLAlchemy validates column references
    - Portable: Works across different database backends
    - Easier to test: Can use ORM test fixtures
    - Better error messages: SQLAlchemy shows what's wrong
    - Refactor-friendly: IDE can track column renames

    **Problem 3: Redundant walrus operator opportunities**

    Multiple places call `.scalar_one_or_none()` and then check `if not result:`,
    when the check could be combined with assignment using the walrus operator.

    **Current implementation (sqlite.py, lines 263-264, 401-402):**
    ```python
    # Line 263-264
    policy = result.scalar_one_or_none()
    if not policy:
        return None

    # Line 401-402
    run = result.scalar_one_or_none()
    if not run:
        return None
    ```

    **The correct approach:**

    Use walrus operator to combine assignment and check:
    ```python
    # Concise version
    if not (policy := result.scalar_one_or_none()):
        return None

    # Or even shorter for simple returns
    if not (run := result.scalar_one_or_none()):
        return None
    ```

    **Problem 4: Unnecessary variable for immediate use**

    Line 246 assigns `policies = result.scalars().all()` but the variable is only
    used once in the immediately following list comprehension. Should inline.

    **Current implementation (sqlite.py, lines 246-255):**
    ```python
    policies = result.scalars().all()
    return [
        PolicyProposal(
            id=str(policy.id),
            status=policy.status,
            created_at=policy.created_at,
            decided_at=policy.decided_at,
            content="",
        )
        for policy in policies
    ]
    ```

    **The correct approach:**

    Inline the variable:
    ```python
    return [
        PolicyProposal(
            id=str(policy.id),
            status=policy.status,
            created_at=policy.created_at,
            decided_at=policy.decided_at,
            content="",
        )
        for policy in result.scalars().all()
    ]
    ```

    **Problem 5: Useless comments documenting removed code**

    Lines 530-533 contain a multi-line comment explaining that old methods were
    removed. This is noise - version control already tracks removed code.

    **Current implementation (sqlite.py, lines 530-533):**
    ```python
    # Policy state management (removed - now handled by unified Policy table above)
    # The old create_policy, get_policy, update_policy, list_policies, delete_policy
    # methods for named/reusable policies have been removed since policies are now
    # per-agent only.
    ```

    **The correct approach:**

    Delete the comment entirely. If context is needed, it's in the commit message
    and git history.

    **Summary of changes:**

    1. Add `comment=` to all mapped_column() calls with inline comments
    2. Rewrite `list_agents_last_activity()` using ORM (func.max, func.coalesce)
    3. Use walrus operator for scalar_one_or_none() + null checks
    4. Inline `policies` variable in list comprehension
    5. Remove comment about removed methods
  |||,
  properties=['use-platform-primitives', 'prefer-concise-code', 'remove-noise'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      [68, 69],   // Inline comments instead of comment= parameter
      [92, 92],   // UUID stored as string comment
      [122, 122], // Sequence number comment
      [125, 126], // Payload and call_id comments
      [150, 152], // Tool call JSON comments
      [203, 203], // MIME type comment
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [145, 165], // Raw SQL instead of ORM for last_activity
      [246, 246], // Unnecessary policies variable
      [263, 264], // policy = ...; if not policy (should walrus)
      [401, 402], // run = ...; if not run (should walrus)
      [530, 533], // Useless comment about removed code
    ],
  },
  gap_note= |||
    This finding illustrates **"use-platform-primitives"**: SQLAlchemy provides
    built-in features (comment=, func.max, func.coalesce) that should be used
    instead of workarounds (inline comments, raw SQL).

    When using ORMs:
    - Use `comment=` for column documentation (visible in DB schema)
    - Use ORM query APIs instead of raw SQL when possible
    - Leverage func.* for SQL functions (max, coalesce, etc.)
    - Trust the ORM to generate correct SQL

    Benefits of ORM over raw SQL:
    - Type safety (catch column name typos)
    - Refactor-friendly (IDE tracks renames)
    - Database portable (works on SQLite, PostgreSQL, etc.)
    - Better testing (can mock/stub ORM objects)
    - Clear errors (SQLAlchemy shows what's wrong where)

    When raw SQL is appropriate:
    - Complex queries that ORM can't express efficiently
    - Database-specific features not in SQLAlchemy
    - Performance-critical paths (with benchmarks proving ORM is slower)
    - Data migrations that operate outside the ORM

    Related to **"prefer-concise-code"**: use walrus operators for check-and-use
    patterns, inline variables only used once.

    Related to **"remove-noise"**: delete comments about removed code (it's in git),
    don't explain what's not there.
  |||,
)
