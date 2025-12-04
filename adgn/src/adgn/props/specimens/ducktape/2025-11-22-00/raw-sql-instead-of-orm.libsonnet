local I = import '../../lib.libsonnet';

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    Query uses raw SQL with `text()` instead of SQLAlchemy ORM constructs, reducing
    type safety and portability.

    **Current code (sqlite.py:145-165):**
    ```python
    def list_agents_last_activity(self) -> dict[AgentID, datetime]:
        result = self.session.execute(text("""
            SELECT agent_id,
                   COALESCE(MAX(created_at), '1970-01-01') as last_activity
            FROM runs
            GROUP BY agent_id
        """))
        return {AgentID(row[0]): datetime.fromisoformat(row[1]) for row in result}
    ```

    **Problems with raw SQL:**
    - Not type-safe (column references as strings)
    - Not portable (SQL syntax may differ across databases)
    - Hard to maintain (refactoring tools don't track column renames)
    - Poor error messages (errors at runtime, not import time)
    - No IDE support (can't navigate to column definitions)

    **Correct approach using ORM:**
    ```python
    from sqlalchemy import func

    def list_agents_last_activity(self) -> dict[AgentID, datetime]:
        result = (
            self.session.query(
                Run.agent_id,
                func.coalesce(func.max(Run.created_at), datetime(1970, 1, 1)).label('last_activity')
            )
            .group_by(Run.agent_id)
            .all()
        )
        return {AgentID(row.agent_id): row.last_activity for row in result}
    ```

    **Benefits:**
    - Type-safe column references
    - Works across database backends
    - Refactoring tools track column renames
    - Better error messages (fails at import if column doesn't exist)
    - IDE can navigate to model definitions
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [145, 165], // Raw SQL instead of ORM for last_activity
    ],
  },
)
