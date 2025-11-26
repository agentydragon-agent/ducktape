local I = import '../../specimens/lib.libsonnet';

// iss-028: SQLAlchemy and database quality issues

I.issueOneOccurrence(
  rationale= |||
    Multiple issues in the SQLAlchemy persistence layer:

    **Problem 1: Inline comments instead of proper SQLAlchemy comments**

    ORM field definitions use inline Python comments (`# MCPConfig as JSON`) instead
    of SQLAlchemy's `comment=` parameter, which would make these descriptions visible
    in the database schema and help DBAs/database tools.

    **The correct approach:**

    Use SQLAlchemy's `comment=` parameter on `mapped_column()` so comments appear
    in database schema (`PRAGMA table_info`, `\d`), database tools show descriptions,
    and migrations preserve documentation.

    **Problem 2: Raw SQL instead of ORM for last_activity query**

    The `list_agents_last_activity()` method uses raw SQL with `text()` instead of
    SQLAlchemy ORM constructs, making it harder to maintain and less portable.

    **The correct approach:**

    Use ORM methods: `func.max()`, `func.coalesce()`, and `.outerjoin()` for type-safe,
    portable queries. ORM validates column references, works across database backends,
    provides better error messages, and IDE can track column renames.

    **Problem 3: Redundant walrus operator opportunities**

    Multiple places call `.scalar_one_or_none()` and then check `if not result:`,
    when the check could be combined with assignment using the walrus operator.

    **The correct approach:**

    Use `if not (var := result.scalar_one_or_none()): return None` to combine
    assignment and check on one line.

    **Problem 4: Unnecessary variable for immediate use**

    Line 246 assigns `policies = result.scalars().all()` but the variable is only
    used once in the immediately following list comprehension.

    **The correct approach:**

    Inline to `for policy in result.scalars().all()` in the comprehension.

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
)
