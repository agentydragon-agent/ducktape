local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    ORM field definitions use inline Python comments instead of SQLAlchemy's `comment=`
    parameter, preventing database schema documentation.

    **Current pattern (models.py, multiple locations):**
    ```python
    mcp_config: Mapped[str]  # MCPConfig as JSON
    run_id: Mapped[str]  # UUID stored as string
    seq: Mapped[int]  # Sequence number within run
    ```

    Inline Python comments are invisible to:
    - Database tools (pgAdmin, DBeaver, etc.)
    - Database introspection (`PRAGMA table_info`, `\d` in psql)
    - Database migrations (Alembic won't preserve them)
    - DBAs inspecting schema

    **Correct approach:**

    Use SQLAlchemy's `comment=` parameter on `mapped_column()`:
    ```python
    mcp_config: Mapped[str] = mapped_column(comment="MCPConfig as JSON")
    run_id: Mapped[str] = mapped_column(comment="UUID stored as string")
    seq: Mapped[int] = mapped_column(comment="Sequence number within run")
    ```

    **Benefits:**
    - Comments visible in database schema
    - Database tools show descriptions
    - Migrations preserve documentation
    - DBAs can understand schema without reading Python code
    - Standard SQLAlchemy feature for schema documentation
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
  },
)
